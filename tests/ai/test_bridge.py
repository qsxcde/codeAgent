"""langchain 编排桥接测试:ChatResponse → AIMessage / 消息归一化 / Runnable 包装。

网络相关测试见 test_transport.py;本文件聚焦 ``ai/bridge/langchain.py`` 的
``to_langchain_ai_message`` / ``_coerce_messages`` / ``to_langchain_runnable``。
"""

from __future__ import annotations

import asyncio

import pytest

from codeagent.ai.bridge.langchain import to_langchain_ai_message


def test_to_langchain_ai_message_bridges_tool_calls_and_usage():
    from codeagent.ai.protocol.messages import ChatResponse, ToolCall

    resp = ChatResponse(
        content="done",
        tool_calls=[ToolCall(id="c1", name="read", arguments='{"p": "x"}')],
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "completion_tokens_details": {"reasoning_tokens": 7},
        },
        finish_reason="stop",
    )
    msg = to_langchain_ai_message(resp)
    assert msg.content == "done"
    assert msg.tool_calls[0]["name"] == "read"
    assert msg.usage_metadata["output_token_details"]["reasoning_tokens"] == 7


def test_coerce_langchain_messages():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from codeagent.ai.bridge.langchain import _coerce_messages

    msgs = _coerce_messages(
        [
            HumanMessage("hi"),
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "read", "args": {"p": "x"}, "type": "tool_call"}]),
            ToolMessage(content="ok", tool_call_id="c1"),
        ]
    )
    assert [m.role for m in msgs] == ["user", "assistant", "tool"]
    assert msgs[1].tool_calls[0].arguments == '{"p": "x"}'
    assert msgs[2].tool_call_id == "c1"


def test_system_role_preserved():
    """SystemMessage 映射为 system 角色,不降级为 user(回归:#2)。"""
    from langchain_core.messages import SystemMessage

    from codeagent.ai.bridge.langchain import _coerce_messages, _map_role

    assert _map_role("system") == "system"
    msgs = _coerce_messages([SystemMessage("你是助手")])
    assert msgs[0].role == "system"


def test_json_decode_error_fallback():
    """不完整 JSON arguments 容错为空 dict,不抛 JSONDecodeError(回归:#1)。"""
    from codeagent.ai.bridge.langchain import to_langchain_ai_message
    from codeagent.ai.protocol.messages import ChatResponse, ToolCall

    msg = to_langchain_ai_message(
        ChatResponse(tool_calls=[ToolCall(id="c1", name="read", arguments="{bad")])
    )
    assert msg.tool_calls[0]["args"] == {}


def test_list_content_preserved():
    """多模态 list content 保留原 list,不 str() 化(回归:#10)。"""
    from codeagent.ai.bridge.langchain import _coerce_content

    assert _coerce_content([{"type": "text", "text": "hi"}]) == [{"type": "text", "text": "hi"}]
    assert _coerce_content("hello") == "hello"
    assert _coerce_content(42) == "42"


@pytest.mark.anyio
async def test_streaming_tool_calls_assembled_end_to_end():
    """流式 tool_calls 跨帧拼接 → finish 后组装完整 ToolCall → AIMessage(#3/#8 端到端)。

    FakeClient.stream 产出 tool_call_arg 事件(参数完整一次性发出),
    to_langchain_runnable.astream 累积后在 finish 产出带完整 tool_calls 的 AIMessage。
    """
    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.providers import FakeClient
    from langchain_core.messages import HumanMessage

    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [{"name": "read", "args": {"file_path": "a.txt"}, "id": "c1"}],
            }
        ]
    )
    bound = to_langchain_runnable(model.bind_tools([]))
    chunks = []
    async for chunk in bound.astream([HumanMessage("读文件")]):
        chunks.append(chunk)

    # 应有带完整 tool_calls 的 AIMessage
    tc_chunks = [c for c in chunks if getattr(c, "tool_calls", None)]
    assert len(tc_chunks) >= 1
    assert tc_chunks[-1].tool_calls[0]["name"] == "read"
    assert tc_chunks[-1].tool_calls[0]["args"] == {"file_path": "a.txt"}


def test_bind_tools_returns_self_then_wraps_to_runnable():
    """bind_tools 记录工具并返回 self;经 to_langchain_runnable 包装后 ainvoke 真实可用(#1 回归)。

    客户端层保持框架无关(返回 self),langchain 包装只在组合根(container.py)发生。
    """
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.providers import FakeClient

    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    def _client(**kwargs) -> OpenAICompatClient:
        base = dict(
            base_url="https://api.deepseek.com",
            api_key="sk-test",
            model="deepseek-v4-flash",
            reasoning_effort="xhigh",
        )
        base.update(kwargs)
        return OpenAICompatClient(**base)

    c = _client()
    bound = c.bind_tools([])
    assert bound is c                       # bind_tools 返回 self
    assert c._tools == []                   # 记录工具后不变(空绑定)

    # 真实执行断言(替换 hasattr 弱断言):FakeClient 离线跑 ainvoke
    fake = FakeClient(response="桥接测试")
    runnable = to_langchain_runnable(fake.bind_tools([]))
    result = asyncio.run(runnable.ainvoke([HumanMessage(content="hi")]))
    assert result.content == "桥接测试"
    assert result.tool_calls == []


def test_runnable_bind_tools_returns_fresh_wrapper():
    """包装上 bind_tools 返回新 wrapper,不污染共享 client,不依赖私有方法(H9/M4)。

    早期缺陷:`_RuntimeRunnable.bind_tools` 委托 ``inner._bind_tools`` 并返回 self,
    两次绑定/并发互相覆盖;本实现把工具挂在 wrapper 上、每次返回新实例。
    """
    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.providers import FakeClient
    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    class T:
        name = "read"
        description = "读文件"

        class args_schema:  # noqa: N801 - 模拟 pydantic Args
            @staticmethod
            def model_json_schema():
                return {"type": "object", "properties": {}}

    tools = [T()]
    real_bound = to_langchain_runnable(
        OpenAICompatClient(base_url="https://api.deepseek.com", api_key="sk-test", model="m")
    )
    rebound = real_bound.bind_tools(tools)
    assert rebound is not real_bound          # 新 wrapper
    assert rebound._tools == tools            # 工具挂在 wrapper 上
    assert real_bound._tools == []            # 原 wrapper 未被污染
    # 两次 bind 互不覆盖
    empty = real_bound.bind_tools([])
    assert empty._tools == []

    fake = FakeClient()
    fake_bound = to_langchain_runnable(fake)
    rebound_fake = fake_bound.bind_tools(tools)
    assert rebound_fake._tools == tools
    assert fake.bound_tools == []             # client 未被改动(绑定隔离在 wrapper)


def test_third_party_protocol_client_bindable():
    """仅实现 ChatClient 公开协议方法的第三方客户端可被包装绑定并生成(H9)。

    早期缺陷:`_RuntimeRunnable.bind_tools` 调私有 ``_bind_tools``,合规客户端
    bind 时 AttributeError;本实现不再依赖私有方法。
    """
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.protocol.messages import ChatResponse

    class ThirdParty:
        @property
        def model_id(self) -> str:
            return "third"

        async def generate(self, messages, tools=None, *, stream=False) -> ChatResponse:
            return ChatResponse(content="ok", finish_reason="stop")

        async def stream(self, messages, tools=None):
            return
            yield  # noqa: B027 - 空流(本测试只走 ainvoke)

        def bind_tools(self, tools):
            return self

    bound = to_langchain_runnable(ThirdParty())
    rebound = bound.bind_tools([object()])       # 不应 AttributeError
    msg = asyncio.run(rebound.ainvoke([HumanMessage("hi")]))
    assert msg.content == "ok"


# -- usage 容错(H1) ---------------------------------------------------------

def test_usage_metadata_partial_does_not_crash():
    """部分 usage(只回 total_tokens)可桥接,不设 usage_metadata,原样进 response_metadata。"""
    from codeagent.ai.protocol.messages import ChatResponse

    msg = to_langchain_ai_message(ChatResponse(content="ok", usage={"total_tokens": 10}))
    assert msg.content == "ok"
    assert msg.usage_metadata is None
    assert msg.response_metadata["usage"] == {"total_tokens": 10}


def test_usage_metadata_none_field_does_not_crash():
    """prompt_tokens 为 None 不再抛 ValidationError(H1)。"""
    from codeagent.ai.protocol.messages import ChatResponse

    msg = to_langchain_ai_message(
        ChatResponse(content="ok", usage={"prompt_tokens": None, "completion_tokens": 5, "total_tokens": 5})
    )
    assert msg.usage_metadata is None


def test_usage_metadata_dirty_type_does_not_crash():
    """usage 字段为脏类型(list/dict/非数值 str)不崩,降级到 response_metadata。"""
    from codeagent.ai.protocol.messages import ChatResponse

    for bad in ([1, 2], {"x": 1}, "abc"):
        msg = to_langchain_ai_message(
            ChatResponse(
                content="ok",
                usage={"prompt_tokens": bad, "completion_tokens": 5, "total_tokens": 5},
            )
        )
        assert msg.usage_metadata is None
        assert msg.response_metadata["usage"]["prompt_tokens"] == bad


def test_usage_non_dict_does_not_crash():
    """usage 非 dict(畸形 provider)不崩,降级到 response_metadata。"""
    from codeagent.ai.protocol.messages import ChatResponse

    msg = to_langchain_ai_message(ChatResponse(content="ok", usage=["not", "dict"]))
    assert msg.usage_metadata is None
    assert msg.response_metadata["usage"] == ["not", "dict"]


def test_usage_numeric_string_coerced():
    """usage 数值字符串正确转 int。"""
    from codeagent.ai.protocol.messages import ChatResponse

    msg = to_langchain_ai_message(
        ChatResponse(
            content="ok",
            usage={"prompt_tokens": "10", "completion_tokens": 5, "total_tokens": 15},
        )
    )
    assert msg.usage_metadata["input_tokens"] == 10


def test_tool_call_arguments_coerced_to_json_string():
    """ToolCall.arguments 强制 JSON 字符串:dict 序列化、空串回退 {}。"""
    from codeagent.ai.protocol.messages import ChatMessage, ToolCall

    tc = ToolCall(id="c1", name="read", arguments={"path": "a"})
    assert tc.arguments == '{"path": "a"}'
    empty = ToolCall(id="c2", name="read", arguments="")
    assert empty.arguments == "{}"
    d = ChatMessage(role="assistant", tool_calls=[tc]).to_api_dict()
    assert d["tool_calls"][0]["function"]["arguments"] == '{"path": "a"}'


def test_coerce_dict_message_preserves_tool_calls():
    """dict 形态消息不再丢 tool_calls/tool_call_id/name。"""
    from codeagent.ai.bridge.langchain import _coerce_messages

    msgs = _coerce_messages(
        [
            {"role": "tool", "content": "ok", "tool_call_id": "c1", "name": "read"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "read", "arguments": '{"p": "a"}'}],
            },
        ]
    )
    assert msgs[0].tool_call_id == "c1"
    assert msgs[0].name == "read"
    assert msgs[1].tool_calls[0].id == "c1"
    assert msgs[1].tool_calls[0].arguments == '{"p": "a"}'


def test_usage_metadata_complete_still_set():
    """三字段齐全仍设 usage_metadata(含细节字段)。"""
    from codeagent.ai.protocol.messages import ChatResponse

    msg = to_langchain_ai_message(
        ChatResponse(
            content="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                   "completion_tokens_details": {"reasoning_tokens": 7}},
        )
    )
    assert msg.usage_metadata["input_tokens"] == 10
    assert msg.usage_metadata["output_token_details"]["reasoning_tokens"] == 7


# -- 流式 tool-call 真实 id(H2) ----------------------------------------------

class _FramedClient:
    """可脚本化产出 StreamEvent 的测试客户端(跨帧/无 finish 等场景)。"""

    def __init__(self, events):
        self._events = events

    async def stream(self, messages, tools=None):
        for e in self._events:
            yield e


async def _collect_astream(bound, msgs):
    return [c async for c in bound.astream(msgs)]


def test_streaming_tool_call_real_id_preserved():
    """供应商给真实 id → 流出真实 id,而非伪造 call_0(H2)。"""
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.protocol.sse import StreamEvent

    bound = to_langchain_runnable(
        _FramedClient(
            [
                StreamEvent(type="tool_call_arg", tool_index=0, arg_delta='{"q": 1}', tool_name="search", tool_id="call_REAL_xyz"),
                StreamEvent(type="finish", finish_reason="tool_calls"),
            ]
        )
    )
    chunks = asyncio.run(_collect_astream(bound, [HumanMessage("hi")]))
    tc = chunks[-1].tool_calls[0]
    assert tc["id"] == "call_REAL_xyz"


def test_streaming_tool_call_args_across_frames():
    """跨帧分片喂参 → 参数累积为完整 JSON;id 跨帧保留(替代一帧给全参)。"""
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.protocol.sse import StreamEvent

    bound = to_langchain_runnable(
        _FramedClient(
            [
                StreamEvent(type="tool_call_arg", tool_index=0, arg_delta='{"file_', tool_name="read", tool_id="c1"),
                StreamEvent(type="tool_call_arg", tool_index=0, arg_delta='path": "a.txt"}'),
                StreamEvent(type="finish", finish_reason="tool_calls"),
            ]
        )
    )
    chunks = asyncio.run(_collect_astream(bound, [HumanMessage("读文件")]))
    tc = chunks[-1].tool_calls[0]
    assert tc["args"] == {"file_path": "a.txt"}
    assert tc["id"] == "c1"


# -- 无 finish 帧兜底(H3) ----------------------------------------------------

def test_streaming_tool_calls_flushed_without_finish():
    """流在无 finish 帧时结束 → 有未决 tool_call 仍 flush,不产出 []。"""
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.protocol.sse import StreamEvent

    bound = to_langchain_runnable(
        _FramedClient(
            [
                StreamEvent(type="tool_call_arg", tool_index=0, arg_delta='{"q": 1}', tool_name="search"),
                # 无 finish 帧,流直接结束
            ]
        )
    )
    chunks = asyncio.run(_collect_astream(bound, [HumanMessage("hi")]))
    tc_chunks = [c for c in chunks if getattr(c, "tool_calls", None)]
    assert tc_chunks, "无 finish 帧也应 flush 出 tool_calls"
    assert tc_chunks[-1].tool_calls[0]["name"] == "search"


# -- 输入归一化(H5) ----------------------------------------------------------

def test_assistant_tool_calls_preserves_narration():
    """带 tool_calls 且 content 非空 → 保留旁白;空 content → null(H7)。"""
    from codeagent.ai.protocol.messages import ChatMessage, ToolCall

    d = ChatMessage(
        role="assistant",
        content="我先查一下",
        tool_calls=[ToolCall(id="c1", name="read", arguments="{}")],
    ).to_api_dict()
    assert d["content"] == "我先查一下"

    empty = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="read", arguments="{}")],
    ).to_api_dict()
    assert empty["content"] is None


def test_coerce_dict_input():
    from codeagent.ai.bridge.langchain import _coerce_messages

    msgs = _coerce_messages({"messages": [{"role": "user", "content": "hi"}]})
    assert msgs[0].role == "user"
    assert msgs[0].content == "hi"


def test_coerce_single_message():
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import _coerce_messages

    msgs = _coerce_messages(HumanMessage("hi"))
    assert msgs[0].role == "user"
    assert msgs[0].content == "hi"


def test_ainvoke_accepts_dict_input():
    """dict 输入经桥接可真实跑通,不抛 AttributeError(H5)。"""
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.providers import FakeClient

    bound = to_langchain_runnable(FakeClient(response="归一化 ok"))
    msg = asyncio.run(bound.ainvoke({"messages": [{"role": "user", "content": "hi"}]}))
    assert msg.content == "归一化 ok"


# -- ToolMessage.name 转发(M3) ----------------------------------------------

def test_tool_message_name_forwarded():
    from langchain_core.messages import ToolMessage

    from codeagent.ai.bridge.langchain import _coerce_messages

    msgs = _coerce_messages([ToolMessage(content="ok", tool_call_id="c1", name="read")])
    assert msgs[0].name == "read"
    assert msgs[0].to_api_dict()["name"] == "read"


# -- finish_reason / model 元数据(L6) ---------------------------------------

def test_finish_reason_and_model_in_response_metadata():
    from codeagent.ai.protocol.messages import ChatResponse

    msg = to_langchain_ai_message(
        ChatResponse(content="x", finish_reason="length", model="deepseek-v4-flash")
    )
    assert msg.response_metadata["finish_reason"] == "length"
    assert msg.response_metadata["model"] == "deepseek-v4-flash"


# -- astream 产出 AIMessageChunk(H4) -----------------------------------------

def test_astream_yields_aimessagechunk_not_aimessage():
    """astream 产出类型为 AIMessageChunk,而非单个完整 AIMessage(H4)。"""
    from langchain_core.messages import AIMessageChunk, HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.providers import FakeClient

    bound = to_langchain_runnable(FakeClient(response="增量"))
    chunks = asyncio.run(_collect_astream(bound, [HumanMessage("hi")]))
    assert chunks
    assert all(isinstance(c, AIMessageChunk) for c in chunks)
    # 所有 chunk 复用同一稳定 id(否则 add_messages 当独立消息追加)
    assert len({getattr(c, "id", None) for c in chunks}) == 1


def test_chunk_addition_merges_not_chatprompttemplate():
    """chunk_a + chunk_b 合并为同一消息,而非退化为 ChatPromptTemplate(H4)。"""
    from langchain_core.messages import AIMessageChunk

    a = AIMessageChunk(content="你", id="s1")
    b = AIMessageChunk(content="好", id="s1")
    merged = a + b
    assert type(merged).__name__ == "AIMessageChunk"
    assert merged.content == "你好"
    assert type(merged).__name__ != "ChatPromptTemplate"


def test_agent_node_aggregates_stream_to_single_message():
    """agent 节点经 astream 消费增量并聚合为单一完整消息(H4)。"""
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.providers import FakeClient
    from codeagent.core.nodes.agent import make_agent_node

    node = make_agent_node(to_langchain_runnable(FakeClient(response="聚合完成")))
    out = asyncio.run(node({"messages": [HumanMessage("hi")]}, config=None))
    msgs = out["messages"]
    assert len(msgs) == 1                       # 单一完整消息
    assert msgs[0].content == "聚合完成"


# -- FakeClient 流式 thinking/usage 分支覆盖(9.2) ----------------------------

def test_fake_stream_emits_thinking_and_usage():
    from langchain_core.messages import HumanMessage

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.providers import FakeClient

    model = FakeClient(
        response="正文",
        thinking="先想一想",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    bound = to_langchain_runnable(model)
    chunks = asyncio.run(_collect_astream(bound, [HumanMessage("hi")]))
    thinking_seen = any(
        (getattr(c, "additional_kwargs", {}) or {}).get("reasoning_content") == "先想一想"
        for c in chunks
    )
    usage_seen = any(
        (getattr(c, "additional_kwargs", {}) or {}).get("usage") for c in chunks
    )
    assert thinking_seen
    assert usage_seen
