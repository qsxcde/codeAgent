"""core 循环测试(自研版):事件序列 / 工具归属 / 递归上限 / 空响应 / steer / 超时。

使用 ``container.ChatModelPort``(正式适配器)把 FakeClient 接入自研循环;
断言事件序列与消息历史的行为,不断言中间表示。
"""

import asyncio

import pytest

from codeagent.app.container import ChatModelPort
from codeagent.core import AgentPorts, EventType, RecursionLimitError, run_turn
from codeagent.core.messages import Message
from codeagent.tools.atomic import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    WriteTool,
)
from codeagent.ai.providers.fake import FakeClient


def _ports(model: FakeClient) -> AgentPorts:
    return AgentPorts(
        model=ChatModelPort(model),
        tools=[ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()],
    )


async def _run(model: FakeClient, prompt: str, **kwargs):
    """跑一轮,返回 (事件类型序列, 事件列表, 消息历史)。"""
    ports = _ports(model)
    events: list = []

    def emit(ev) -> None:
        events.append(ev)

    history = await run_turn(
        ports, emit, prompt, history=[], recursion_limit=kwargs.pop("recursion_limit", 50), **kwargs
    )
    return [e.type for e in events], events, history


def test_direct_reply_ends_loop():
    """直接回复:单条 assistant,无工具调用。"""
    model = FakeClient(response="你好")
    types, events, history = asyncio.run(_run(model, "hi"))
    assert EventType.TEXT_DELTA in types
    assert EventType.TOOL_CALL not in types
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[-1].content == "你好"


def test_single_tool_error_attached_and_flagged():
    """单工具失败:结果带错误标记,归属到对应 assistant 之后。"""
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "read", "args": {"file_path": "missing.py"}, "id": "c1", "type": "tool_call"}
                ],
            },
            {"content": "文件不存在,已处理"},
        ]
    )
    types, events, history = asyncio.run(_run(model, "读"))
    assert EventType.TOOL_CALL in types and EventType.TOOL_RESULT in types
    assert EventType.TEXT_DELTA in types
    result = next(e for e in events if e.type == EventType.TOOL_RESULT)
    assert result.metadata["tool_call_id"] == "c1"
    assert result.metadata["error"] is True
    roles = [m.role for m in history]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert history[2].tool_call_id == "c1"


def test_parallel_tools_ok_and_fail():
    """并行双工具(一成一败):按 calls 顺序归属,错误互不污染。"""
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "bash", "args": {"command": "echo ok"}, "id": "c-ok", "type": "tool_call"},
                    {"name": "read", "args": {"file_path": "/nonexistent/x.py"}, "id": "c-bad", "type": "tool_call"},
                ],
            },
            {"content": "并行结果"},
        ]
    )
    _, events, history = asyncio.run(_run(model, "并行"))
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    by_id = {e.metadata["tool_call_id"]: e for e in results}
    assert set(by_id) == {"c-ok", "c-bad"}
    assert by_id["c-ok"].metadata["error"] is False
    assert by_id["c-bad"].metadata["error"] is True
    # 消息序列:user → assistant → tool(c-ok) → tool(c-bad) → assistant
    assert [m.role for m in history] == ["user", "assistant", "tool", "tool", "assistant"]
    assert history[2].tool_call_id == "c-ok" and history[3].tool_call_id == "c-bad"


def test_three_rounds_loop():
    """三轮 ReAct:两次工具调用后最终回复。"""
    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo one"}, "id": "r1", "type": "tool_call"}]},
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo two"}, "id": "r2", "type": "tool_call"}]},
            {"content": "三轮结束"},
        ]
    )
    types, _, history = asyncio.run(_run(model, "开始"))
    assert types.count(EventType.TOOL_CALL) == 2
    assert types.count(EventType.TOOL_RESULT) == 2
    assert history[-1].content == "三轮结束"
    assert sum(1 for m in history if m.role == "tool") == 2


def test_empty_response_emits_agent_message():
    """空响应兜底:AGENT_MESSAGE(''),无 TEXT_DELTA。"""
    model = FakeClient(response="")
    types, _, history = asyncio.run(_run(model, "空"))
    assert EventType.AGENT_MESSAGE in types
    assert EventType.TEXT_DELTA not in types
    assert history[-1].role == "assistant" and history[-1].content == ""


def test_recursion_limit_raises_friendly():
    """循环超限:抛 RecursionLimitError,友好提示。"""
    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo x"}, "id": f"r{i}", "type": "tool_call"}]}
            for i in range(10)
        ]
    )
    with pytest.raises(RecursionLimitError) as exc:
        asyncio.run(_run(model, "循环", recursion_limit=3))
    assert "次数过多" in str(exc.value)


def test_steer_injection_consumed_before_next_round():
    """steer 注入:运行中注入的消息在下一轮循环前消费为 user 消息。"""
    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo a"}, "id": "s1", "type": "tool_call"}]},
            {"content": "最终回复"},
        ]
    )
    ports = _ports(model)
    queue: asyncio.Queue[str] = asyncio.Queue()
    queue.put_nowait("运行中注入")
    events: list = []

    async def run() -> list[Message]:
        return await run_turn(ports, events.append, "开始", history=[], inject_queue=queue)

    history = asyncio.run(run())
    # 注入消息成为第二轮前的 user 消息(在首条 user 之后、首个 assistant 之前?不——
    # drain 在每轮循环前,第一轮前已有注入 → 紧随首条 user)
    users = [m for m in history if m.role == "user"]
    assert [m.content for m in users] == ["开始", "运行中注入"]


def test_tool_timeout_marks_error():
    """工具超时:超时结果按错误处理,循环继续。"""
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "bash", "args": {"command": "sleep 5"}, "id": "t1", "type": "tool_call"}
                ],
            },
            {"content": "超时了"},
        ]
    )
    _, events, history = asyncio.run(_run(model, "超时", tool_timeout=0.2))
    result = next(e for e in events if e.type == EventType.TOOL_RESULT)
    assert result.metadata["error"] is True
    assert history[-1].content == "超时了"


def test_model_failure_propagates():
    """模型抛错:异常传播给调用方(事件壳负责回滚与 ERROR)。"""

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("模型炸了")

    with pytest.raises(RuntimeError, match="模型炸了"):
        asyncio.run(_run(BoomModel(response="x"), "触发"))
