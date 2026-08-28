"""OpenAI 兼容协议的模型传输层(deepseek / openai / ollama 等)。

- 直接构造 ``/chat/completions`` 请求体,``reasoning_effort`` 原样上传;
- 流式走自研 SSE 解析(``ai/transport/sse.py``),thinking / usage 全量透传;
- 依赖 ``httpx``(轻量 HTTP 客户端),不加载重型 SDK;
- 框架无关:不 import LangChain,由组合根把客户端适配到自研编排所需的模型端口。
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from codeagent.ai.model.types import (
    ChatMessage,
    ChatResponse,
    StreamEvent,
    ToolCall,
    ToolDefinition,
)
from codeagent.ai.transport.streaming import OpenAICompatStreamingMixin


#: 工具定义 → OpenAI function calling schema。
def _tool_schema(tool: ToolDefinition) -> dict[str, Any]:
    return tool.to_api_dict()


class OpenAICompatClient(OpenAICompatStreamingMixin):
    """OpenAI 兼容协议的模型客户端(deepseek / openai / ollama 等)。

    - 直接构造 ``/chat/completions`` 请求体,``reasoning_effort`` 原样上传;
    - 流式走自研 SSE 解析(``ai/transport/sse.py``),thinking / usage 全量透传;
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
        parsed_url = urlsplit(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("base_url 必须是带主机名的 http/https URL")
        if parsed_url.query or parsed_url.fragment:
            raise ValueError("base_url 不得包含 query 或 fragment")
        if max_tokens is not None and (
            type(max_tokens) is not int or max_tokens < 1
        ):
            raise ValueError("max_tokens 必须是正整数")
        if reasoning_effort is not None and reasoning_effort not in {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        }:
            raise ValueError("reasoning_effort 必须是 low/medium/high/xhigh/max/ultra")
        self._base_url = base_url.rstrip("/")
        # 统一存 SecretStr:repr/日志/回溯不泄露明文(M7)
        self._api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._max_tokens = max_tokens
        self._temperature = temperature
        # 非流式请求必须有有限的 read timeout；流式请求另行允许较长的
        # 首 token 等待，避免服务端 accept 后永远不返回导致 TUI 假死。
        if timeout is None:
            self._timeout = httpx.Timeout(
                connect=10.0, read=120.0, write=30.0, pool=10.0
            )
            self._stream_timeout = httpx.Timeout(
                connect=10.0, read=None, write=30.0, pool=10.0
            )
        elif isinstance(timeout, httpx.Timeout):
            self._timeout = timeout
            self._stream_timeout = timeout
        else:
            # float: 向后兼容(全部操作同一超时)
            self._timeout = httpx.Timeout(timeout)
            self._stream_timeout = self._timeout
        self._max_retries = max_retries
        self._default_tools: tuple[ToolDefinition, ...] = ()
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

    def bind_tools(self, tools: list[ToolDefinition]) -> "OpenAICompatClient":
        """Return an isolated compatibility view with immutable default tools."""
        bound = copy.copy(self)
        bound._default_tools = tuple(tools)
        return bound

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
        tools: list[ToolDefinition] | None = None,
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
        effective_tools = self._default_tools if tools is None else tuple(tools)
        if effective_tools:
            body["tools"] = [_tool_schema(t) for t in effective_tools]
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
        tools: list[ToolDefinition] | None = None,
        *,
        stream: bool = False,
    ) -> ChatResponse:
        """非流式:一次请求拿完整响应(含指数退避重试);stream=True 走流式并聚合(M5)。"""
        if stream:
            return await self._generate_streaming(messages, tools)
        body = self._body(messages, stream=False, tools=tools)

        client = self._get_client()
        for attempt in range(self._max_retries + 1):
            try:
                resp = await client.post(
                    self._endpoint(),
                    headers=self._headers(),
                    json=body,
                    timeout=self._timeout,
                )
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
