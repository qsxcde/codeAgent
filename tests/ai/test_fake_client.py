"""FakeClient 测试:脚本消费、usage 注入、bind_tools 占位、离线不联网。"""

import asyncio

from codeagent.ai.providers.fake import FakeClient
from codeagent.ai.model.types import ChatMessage


def _msg(content: str = "hi") -> list[ChatMessage]:
    return [ChatMessage(role="user", content=content)]


async def test_returns_fixed_response():
    client = FakeClient(response="你好")
    resp = await (client.generate(_msg("你是谁")))
    assert resp.content == "你好"


async def test_returns_scripted_responses():
    client = FakeClient(response="兜底", responses=["第一轮", "第二轮"])
    assert (await client.generate(_msg("1"))).content == "第一轮"
    assert (await client.generate(_msg("2"))).content == "第二轮"
    # 耗尽后回落到 response
    assert (await client.generate(_msg("3"))).content == "兜底"


async def test_steps_consume_tool_calls():
    client = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "read", "args": {"file_path": "a"}, "id": "c1"}]},
            {"content": "完成"},
        ]
    )
    r1 = await (client.generate(_msg("调工具")))
    assert r1.tool_calls and r1.tool_calls[0].name == "read"
    assert r1.tool_calls[0].arguments == '{"file_path": "a"}'
    r2 = await (client.generate(_msg("继续")))
    assert r2.content == "完成"


async def test_usage_injected():
    client = FakeClient(
        response="ok",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    resp = await (client.generate(_msg()))
    assert resp.usage["total_tokens"] == 15


def test_bind_tools_records_names():
    class T:
        name = "read"

    client = FakeClient()
    client.bind_tools([T()])
    assert client.bound_tools == ["read"]


async def test_offline_no_network():
    """FakeClient 不发起任何网络请求(无 httpx 依赖路径)。"""
    client = FakeClient(response="离线")
    resp = await (client.generate(_msg()))
    assert resp.content == "离线"
    assert client.call_history  # 记录了调用,供断言


async def test_generate_hook_can_be_overridden():
    """子类覆盖 _generate 抛异常 → generate 透传(供编排错误路径测试)。"""

    class Boom(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("图炸了")

    client = Boom()
    try:
        await (client.generate(_msg()))
    except RuntimeError as exc:
        assert "图炸了" in str(exc)
    else:  # pragma: no cover - 不应走到
        raise AssertionError("应当抛异常")
