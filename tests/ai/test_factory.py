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


def test_fake_bind_tools_records_then_runs_via_model_port():
    """bind_tools 记录工具名;经组合根 ChatModelPort 适配后自研循环可消费。"""
    from codeagent.app.container import ChatModelPort

    model = FakeClient(response="绑定测试")

    class FakeTool:
        name = "read"

    model.bind_tools([FakeTool()])
    assert model.bound_tools == ["read"]
    port = ChatModelPort(model)
    assert port.model_id == "fake-model"
