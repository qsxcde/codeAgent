"""OpenAI 兼容协议的模型传输层(deepseek / openai / ollama 等)。

- 直接构造 ``/chat/completions`` 请求体,``reasoning_effort`` 原样上传;
- 流式走自研 SSE 解析(``ai/protocol/sse.py``),thinking / usage 全量透传;
- 依赖 ``httpx``(轻量 HTTP 客户端),不加载重型 SDK;
- 框架无关:不 import langchain,编排桥接由组合根经 ``ai/bridge/langchain.py`` 包装。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

import httpx
from pydantic import SecretStr

from codeagent.ai.protocol.messages import ChatMessage, ChatResponse, ToolCall
from codeagent.ai.protocol.sse import SSEParser, StreamEvent


#: 工具 → OpenAI function calling schema(原子工具已含 name/description/Args)。
def _tool_schema(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", ""),
            "parameters": _args_schema(getattr(tool, "args_schema", None)),
        },
    }


def _args_schema(args_schema: Any) -> dict[str, Any]:
    """从工具的 pydantic Args 生成 JSON Schema;取不到时给宽松的 object。"""
    schema = getattr(args_schema, "model_json_schema", None)
    if schema:
        try:
            return schema()
        except Exception:  # noqa: BLE001 - 容错:个别 schema 生成失败给宽松格式
            pass
    return {"type": "object", "properties": {}}


class OpenAICompatClient:
    """OpenAI 兼容协议的模型客户端(deepseek / openai / ollama 等)。

    - 直接构造 ``/chat/completions`` 请求体,``reasoning_effort`` 原样上传;
    - 流式走自研 SSE 解析(``ai/protocol/sse.py``),thinking / usage 全量透传;
    - 依赖 ``httpx``(轻量 HTTP 客户端),不加载重型 SDK。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr | str,
        model: str,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # 统一存 SecretStr:repr/日志/回溯不泄露明文(M7)
        self._api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._max_tokens = max_tokens
        self._temperature = temperature
        # 区分 connect/read 超时:流式首 token 可能很久(xhigh 思考),read 不限制
        if timeout is None:
            self._timeout: httpx.Timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        elif isinstance(timeout, httpx.Timeout):
            self._timeout = timeout
        else:
            # float: 向后兼容(全部操作同一超时)
            self._timeout = httpx.Timeout(timeout)
        self._max_retries = max_retries
        self._tools: list[Any] = []
        #: 复用的底层 HTTP 客户端(懒创建,提供 aclose 释放);连接/TLS 复用(M6)。
        self._client: httpx.AsyncClient | None = None

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def reasoning_effort(self) -> str | None:
        """当前思考强度(构造时配置或覆盖后的值)。"""
        return self._reasoning_effort

    @property
    def max_tokens(self) -> int | None:
        return self._max_tokens

    def _get_client(self) -> httpx.AsyncClient:
        """懒创建单一 AsyncClient(供 generate/stream 复用)。"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        """释放底层连接(幂等)。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _bind_tools(self, tools: list[Any]) -> None:
        """仅记录工具(构造请求体时转成 function calling schema)。"""
        self._tools = list(tools)

    def bind_tools(self, tools: list[Any]) -> "OpenAICompatClient":
        """记录工具并返回 self(框架无关;编排适配由组合根 ChatModelPort 负责)。

        - 组合根(container.py)拿到 self 后再 ``to_langchain_runnable`` 包装,
          得到供 LangGraph 消费的 ``bound_model``;
        - 内部 ``generate``/``stream`` 走 ``_bind_tools``,避免热路径重复记录。
        """
        self._bind_tools(tools)
        return self

    # -- 请求构造 ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    def _endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _body(
        self,
        messages: list[ChatMessage],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [m.to_api_dict() for m in messages],
            "stream": stream,
        }
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort
        if self._max_tokens:
            body["max_tokens"] = self._max_tokens
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if stream:
            # 请求 usage 增量(OpenAI 兼容端点),供 SSE 解析器 usage 事件透传(M2)
            body["stream_options"] = {"include_usage": True}
        if self._tools:
            body["tools"] = [_tool_schema(t) for t in self._tools]
            body["tool_choice"] = "auto"
        return body

    # -- 调用 --------------------------------------------------------------

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """429 / 5xx / 传输层错误可重试;4xx(除 429)不重试。"""
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status == 429 or status >= 500
        return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[Any] | None = None,
        *,
        stream: bool = False,
    ) -> ChatResponse:
        """非流式:一次请求拿完整响应(含指数退避重试);stream=True 走流式并聚合(M5)。"""
        if stream:
            return await self._generate_streaming(messages, tools)
        if tools is not None:
            self._bind_tools(tools)
        body = self._body(messages, stream=False)

        client = self._get_client()
        for attempt in range(self._max_retries + 1):
            try:
                resp = await client.post(self._endpoint(), headers=self._headers(), json=body)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:  # noqa: BLE001 - 重试判定
                if attempt == self._max_retries or not self._is_retryable(exc):
                    raise
                await asyncio.sleep(min(2 ** attempt, 10.0))

        tool_calls: list[ToolCall] = []
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments", "{}"),
                )
            )
        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            usage=data.get("usage"),
            finish_reason=choice.get("finish_reason"),
            model=self._model,
        )

    async def _generate_streaming(
        self,
        messages: list[ChatMessage],
        tools: list[Any] | None,
    ) -> ChatResponse:
        """generate(stream=True) 真实生效:走流式请求并聚合成完整 ChatResponse(M5)。"""
        parser = SSEParser()
        content_parts: list[str] = []
        usage: dict[str, Any] | None = None
        finish_reason: str | None = None
        async for event in self.stream(messages, tools):
            if event.type == "content":
                content_parts.append(event.text)
            elif event.type == "tool_call_arg":
                fn: dict[str, Any] = {"arguments": event.arg_delta}
                if event.tool_name:
                    fn["name"] = event.tool_name
                frame: dict[str, Any] = {"function": fn}
                if event.tool_id:
                    frame["id"] = event.tool_id
                parser.feed(
                    json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "tool_calls": [
                                            {"index": event.tool_index or 0, **frame}
                                        ]
                                    }
                                }
                            ]
                        }
                    )
                )
            elif event.type == "usage":
                usage = event.usage
            elif event.type == "finish":
                finish_reason = event.finish_reason
        assembled = parser.assembled_tool_calls()
        tool_calls = [
            ToolCall(
                id=tc.get("id") or uuid.uuid4().hex,
                name=tc["name"],
                arguments=tc["arguments"],
            )
            for tc in assembled
        ]
        return ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
            model=self._model,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式:SSE 解析逐帧产出事件;connect+首帧纳入指数退避重试(H6)。

        - 未读 body 先 ``aread()`` 再 ``raise_for_status()``,错误细节(401/429/500
          的具体信息)不丢失;
        - 收到首帧内容后不再重试(避免重复消耗上游 token / 重复产出事件)。
        """
        if tools is not None:
            self._bind_tools(tools)
        body = self._body(messages, stream=True)

        parser = SSEParser()

        def _emit(data: str) -> list[StreamEvent]:
            """解析一帧拼接后的 data 内容;`[DONE]` 不产出事件。"""
            data = data.strip()
            if not data or data == "[DONE]":
                return []
            return parser.feed(data)

        client = self._get_client()
        yielded = False
        for attempt in range(self._max_retries + 1):
            try:
                async with client.stream(
                    "POST", self._endpoint(), headers=self._headers(), json=body
                ) as resp:
                    # 先读 body 再 raise:错误细节不因 body 未读而丢失
                    if not resp.is_success:
                        await resp.aread()
                    resp.raise_for_status()
                    # 按 SSE 规范:同一事件的 data 行用 \n 拼接,空行表示帧结束。
                    # 额外容忍供应商差异:帧间无空行的连续 data 行、[DONE] 独立行、
                    # 末帧无空行即断开(连接关闭时残留 buffer 需 flush)。
                    buffer: list[str] = []
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            # 空行 = 帧结束,拼接多行 data 后解析
                            if line == "" and buffer:
                                joined = "\n".join(buffer)
                                buffer = []
                                for event in _emit(joined):
                                    yielded = True
                                    yield event
                            continue
                        payload = line[len("data:"):].lstrip(" ")
                        if payload == "[DONE]":
                            # [DONE] 是独立事件边界:先 flush 前一帧再终止
                            if buffer:
                                joined = "\n".join(buffer)
                                buffer = []
                                for event in _emit(joined):
                                    yielded = True
                                    yield event
                            return
                        if buffer:
                            # buffer 已是完整 JSON 帧 → 先 flush,再累积新帧(容忍帧间无空行)
                            try:
                                json.loads("\n".join(buffer))
                            except json.JSONDecodeError:
                                pass  # 跨行 JSON 半帧,继续累积
                            else:
                                joined = "\n".join(buffer)
                                buffer = []
                                for event in _emit(joined):
                                    yielded = True
                                    yield event
                        buffer.append(payload)
                    # 流结束(aiter_lines 耗尽)后 flush 残留 buffer(末帧无空行即断开)
                    if buffer:
                        joined = "\n".join(buffer)
                        buffer = []
                        for event in _emit(joined):
                            yielded = True
                            yield event
                return
            except Exception as exc:  # noqa: BLE001 - 重试判定
                if yielded or not self._is_retryable(exc):
                    raise
                if attempt == self._max_retries:
                    raise
                await asyncio.sleep(min(2 ** attempt, 10.0))
