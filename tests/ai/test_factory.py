"""ai 层测试:FakeClient 离线行为(不联网、不耗 key)。

测试直接使用自研客户端接口(``generate``/``bind_tools``),不依赖 langchain。
"""

import asyncio

from codeagent.ai.providers import FakeClient
from codeagent.ai.protocol.messages import ChatMessage


def _msgs(*contents: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=c) for c in contents]


def test_fake_returns_fixed_response():
    model = FakeClient(response="你好")
    resp = asyncio.run(model.generate(_msgs("你是谁")))
    assert resp.content == "你好"


def test_fake_returns_scripted_responses():
    model = FakeClient(response="兜底", responses=["第一轮", "第二轮"])
    assert asyncio.run(model.generate(_msgs("1"))).content == "第一轮"
    assert asyncio.run(model.generate(_msgs("2"))).content == "第二轮"
    # 耗尽后回落到 response
    assert asyncio.run(model.generate(_msgs("3"))).content == "兜底"


def test_fake_can_emit_tool_calls():
    model = FakeClient(
        tool_calls=[
            {
                "name": "read_file",
                "args": {"path": "README.md"},
                "id": "call_1",
                "type": "tool_call",
            }
        ]
    )
    resp = asyncio.run(model.generate(_msgs("读文件")))
    assert resp.tool_calls and resp.tool_calls[0].name == "read_file"
    assert resp.finish_reason == "tool_calls"


def test_fake_bind_tools_records_then_wraps_to_runnable():
    """bind_tools 记录工具并返回 self;经 to_langchain_runnable 包装后有 ainvoke。"""
    from codeagent.ai.bridge.langchain import to_langchain_runnable

    model = FakeClient(response="绑定测试")

    class FakeTool:
        name = "read"

    bound = to_langchain_runnable(model.bind_tools([FakeTool()]))
    assert model.bound_tools == ["read"]
    # 真实执行断言(替换 hasattr 弱断言):ainvoke 实际返回绑定响应
    from langchain_core.messages import HumanMessage

    resp = asyncio.run(bound.ainvoke([HumanMessage(content="hi")]))
    assert resp.content == "绑定测试"
