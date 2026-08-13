"""LangChain 编排桥接层:把自研 ``ChatClient`` / ``ChatResponse`` 包装为 langchain 对象。

- ``to_langchain_ai_message``:``ChatResponse`` → langchain ``AIMessage``
  (含 tool_calls / usage_metadata);
- ``to_langchain_runnable``:``ChatClient`` → langchain Runnable(ainvoke / astream),
  供保留的 langgraph 编排层无改动消费(见 design D5);
- 只被组合根(container.py)与测试消费,``ai/`` 内部其余模块不 import 本层。
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator

from codeagent.ai.protocol.messages import ChatMessage, ChatResponse, ToolCall
from codeagent.ai.protocol.sse import SSEParser

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import Runnable

    from codeagent.ai.protocol.messages import ChatClient


def _is_int_like(value: Any) -> bool:
    """usage 数值是否可转 int(bool/int/float/数值字符串)。"""
    if isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        try:
            int(value)
            return True
        except ValueError:
            return False
    return False


def _as_int(value: Any) -> int:
    """把已通过 _is_int_like 的值转 int(bool 显式 0/1)。"""
    return int(value)


def to_langchain_ai_message(resp: ChatResponse) -> "AIMessage":
    """把自研 ``ChatResponse`` 转成 langchain ``AIMessage``(编排桥接)。"""
    from langchain_core.messages import AIMessage

    kwargs: dict[str, Any] = {"content": resp.content}
    if resp.tool_calls:
        tool_calls_list = []
        for tc in resp.tool_calls:
            try:
                args = json.loads(tc.arguments) if tc.arguments else {}
            except json.JSONDecodeError:
                # 容错:流式聚合不完整/供应商返回截断 JSON 时回退为空 dict,不崩图
                args = {}
            tool_calls_list.append(
                {"id": tc.id, "name": tc.name, "args": args, "type": "tool_call"}
            )
        kwargs["tool_calls"] = tool_calls_list
    metadata: dict[str, Any] = {}
    if resp.usage:
        if not isinstance(resp.usage, dict):
            # 畸形 usage(非 dict):降级到 response_metadata,不崩
            metadata["usage"] = resp.usage
        else:
            input_tokens = resp.usage.get("prompt_tokens")
            output_tokens = resp.usage.get("completion_tokens")
            total_tokens = resp.usage.get("total_tokens")
            if (
                _is_int_like(input_tokens)
                and _is_int_like(output_tokens)
                and _is_int_like(total_tokens)
            ):
                # 三个核心字段均可转 int:设 usage_metadata(逐字段类型容错)
                usage_metadata: dict[str, Any] = {
                    "input_tokens": _as_int(input_tokens),
                    "output_tokens": _as_int(output_tokens),
                    "total_tokens": _as_int(total_tokens),
                }
                if isinstance(resp.usage.get("prompt_tokens_details"), dict):
                    usage_metadata["input_token_details"] = resp.usage["prompt_tokens_details"]
                if isinstance(resp.usage.get("completion_tokens_details"), dict):
                    usage_metadata["output_token_details"] = resp.usage["completion_tokens_details"]
                kwargs["usage_metadata"] = usage_metadata
            else:
                # 部分/脏类型 usage:不设 usage_metadata(AIMessage pydantic 会拒绝
                # None 与非数值),原样放入 response_metadata
                metadata["usage"] = resp.usage
    if resp.finish_reason:
        metadata["finish_reason"] = resp.finish_reason
    if resp.model:
        metadata["model"] = resp.model
    if metadata:
        kwargs["response_metadata"] = metadata
    return AIMessage(**kwargs)


def to_langchain_runnable(client: ChatClient) -> "Runnable":
    """把自研客户端包装成 langchain Runnable,供编排层无改动消费。

    内部委托自研 ``generate``/``stream``,返回 langchain ``AIMessage``
    (含 tool_calls / usage_metadata)。保留 ``bind_tools`` 语义。
    """
    from langchain_core.runnables import Runnable

    class _RuntimeRunnable(Runnable):
        def __init__(self, inner: ChatClient, tools: list[Any] | None = None) -> None:
            self._inner = inner
            self._tools = list(tools or [])

        def bind_tools(self, tools: list[Any], **kwargs: Any) -> "_RuntimeRunnable":
            # 返回新 wrapper:工具挂在 wrapper 上,不污染共享 client,也不依赖私有方法(H9/M4)
            return _RuntimeRunnable(self._inner, tools=tools)

        async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            messages = _coerce_messages(input)
            resp = await self._inner.generate(messages, tools=self._tools or None)
            return to_langchain_ai_message(resp)

        async def astream(self, input: Any, config: Any = None, **kwargs: Any) -> AsyncIterator[Any]:
            """流式:逐增量产出 AIMessageChunk,finish/流结束后组装完整 tool_calls。

            - 所有 chunk 复用同一稳定 ``id``(否则 add_messages 把每段当独立消息追加);
            - content/thinking/usage 增量块逐帧产出;
            - tool_call_arg 喂入本地 parser 累积,finish/流结束 flush 时产出
              带完整 tool_calls(经 tool_call_chunks 表达,供 add_messages 正确归约);
            - 产出类型一律为 ``AIMessageChunk``(而非完整 ``AIMessage``)。
            """
            from langchain_core.messages import AIMessageChunk

            messages = _coerce_messages(input)
            chunk_id = uuid.uuid4().hex  # 稳定 id:全流共用,保证归约为同一消息

            def _tool_calls_chunk(assembled: list[dict]) -> Any:
                """把 parser 累积结果组装成带完整 tool_calls 的 AIMessageChunk。"""
                tool_call_chunks = []
                for index, tc in enumerate(assembled):
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}  # 流式聚合不完整/供应商返回截断 JSON 时回退为空 dict
                    tool_call_chunks.append(
                        {
                            # 真实 id 优先;缺失回退 UUID(不再自造 call_{i},流式/非流式一致)
                            "id": tc.get("id") or uuid.uuid4().hex,
                            "name": tc["name"],
                            "args": json.dumps(args, ensure_ascii=False),
                            "index": index,
                            "type": "tool_call_chunk",
                        }
                    )
                return AIMessageChunk(content="", tool_call_chunks=tool_call_chunks, id=chunk_id)

            parser = SSEParser()
            tool_calls_emitted = False  # finish 已 flush 后避免循环末二次 emit
            async for event in self._inner.stream(messages, tools=self._tools or None):
                if event.type == "content":
                    yield AIMessageChunk(content=event.text, id=chunk_id)
                elif event.type == "thinking":
                    yield AIMessageChunk(
                        content="",
                        additional_kwargs={"reasoning_content": event.text},
                        id=chunk_id,
                    )
                elif event.type == "tool_call_arg":
                    # 喂入本地 parser 累积(含 name/id 首帧)
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
                    yield AIMessageChunk(
                        content="",
                        additional_kwargs={"usage": event.usage},
                        id=chunk_id,
                    )
                elif event.type == "finish":
                    # finish 后组装完整 tool_calls
                    assembled = parser.assembled_tool_calls()
                    if assembled:
                        yield _tool_calls_chunk(assembled)
                        tool_calls_emitted = True
                    else:
                        yield AIMessageChunk(
                            content="",
                            response_metadata={"finish_reason": event.finish_reason},
                            id=chunk_id,
                        )
            # 流结束(含无 finish 帧)兜底:有未决 tool_call 且尚未 flush 时补一次(H3)
            if parser.has_pending and not tool_calls_emitted:
                assembled = parser.assembled_tool_calls()
                if assembled:
                    yield _tool_calls_chunk(assembled)

        def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            raise RuntimeError("编排层使用异步接口;同步调用请用 asyncio.run(client.ainvoke(...))")

        @property
        def name(self) -> str:
            return getattr(self._inner, "model_id", "runtime")

    return _RuntimeRunnable(client)


def _coerce_content(content: Any) -> Any:
    """content 为 str/list 时保留原值;其它类型转 str 兜底。"""
    if isinstance(content, (str, list)):
        return content
    return str(content)


def _coerce_messages(input: Any) -> list[ChatMessage]:
    """把编排层传入的消息序列转成自研 ``ChatMessage`` 列表。

    输入形态归一化(H5):``{"messages": [...]}`` 字典 / ``PromptValue`` /
    单条 ``BaseMessage`` 统一转为消息列表。
    content 为 list(多模态内容块)时保留原 list,不 str() 化(OpenAI API 支持);
    content 为其它非 str 类型时转 str 兜底。
    """
    from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

    # 输入形态归一化
    if isinstance(input, dict):
        if "messages" in input:
            input = input["messages"]
        elif "role" in input:
            input = [input]  # 单条 dict 消息
    if hasattr(input, "to_messages"):
        input = input.to_messages()  # PromptValue 等
    elif isinstance(input, BaseMessage):
        input = [input]  # 单条 BaseMessage

    out: list[ChatMessage] = []
    for m in input or []:
        if not isinstance(m, BaseMessage):
            # 兼容 dict 形态(含 tool_calls / tool_call_id / name,不再丢弃)
            tool_calls = [
                ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments") or "{}",
                )
                for tc in m.get("tool_calls") or []
            ]
            out.append(
                ChatMessage(
                    role=m.get("role", "user"),
                    content=_coerce_content(m.get("content", "")),
                    tool_calls=tool_calls,
                    tool_call_id=m.get("tool_call_id", ""),
                    name=m.get("name", ""),
                )
            )
            continue
        role = m.type  # human → user / ai → assistant / tool → tool
        if isinstance(m, ToolMessage):
            out.append(
                ChatMessage(
                    role="tool",
                    content=_coerce_content(m.content),
                    tool_call_id=m.tool_call_id,
                    name=getattr(m, "name", ""),
                )
            )
        elif isinstance(m, AIMessage):
            tool_calls = [
                ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=json.dumps(tc.get("args", {}), ensure_ascii=False),
                )
                for tc in getattr(m, "tool_calls", None) or []
            ]
            out.append(
                ChatMessage(
                    role="assistant",
                    content=_coerce_content(m.content),
                    tool_calls=tool_calls,
                )
            )
        else:
            # langchain 的 type: human→user;system 保留;ai→assistant(上面已处理)
            out.append(ChatMessage(role=_map_role(role), content=_coerce_content(m.content)))
    return out


def _map_role(role: str) -> str:
    """langchain 消息类型 → OpenAI chat 角色。

    human → user;ai → assistant;system/tool 等原样保留(OpenAI 协议有独立角色)。
    """
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    return role
