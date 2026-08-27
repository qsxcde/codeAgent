"""Agent Runtime 循环行为测试。

旧的端口/整轮入口测试已迁移到纯内存 Agent 契约；会话确认
和持久化行为由 session 测试覆盖。
"""

from __future__ import annotations

import asyncio

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import (
    AgentContext,
    AgentLoopConfig,
    EventType,
    RecursionLimitError,
    ToolDecision,
    ToolExecutionRuntime,
    ToolCall,
    run_agent_loop,
)
from codeagent.tools.atomic import BashTool, ReadTool


def _config(model: FakeClient, *, before_tool_call=None, tool_timeout=None):
    return AgentLoopConfig(
        model=ChatModelPort(model),
        tools=[ReadTool(), BashTool()],
        before_tool_call=before_tool_call,
        tool_timeout=tool_timeout,
    )


async def test_direct_reply_returns_only_new_runtime_messages():
    events: list = []
    messages = await (
        run_agent_loop(
            AgentContext(), _config(FakeClient(response="你好")), "hi", emit=events.append
        )
    )

    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[-1].content == "你好"
    assert [event.type for event in events].count(EventType.AGENT_START) == 1
    assert EventType.MESSAGE_UPDATE in [event.type for event in events]


async def test_tool_results_follow_call_order_and_continue_generation():
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "bash", "args": {"command": "echo ok"}, "id": "c1"},
                    {"name": "read", "args": {"file_path": "missing.py"}, "id": "c2"},
                ],
            },
            {"content": "完成"},
        ]
    )
    events: list = []
    messages = await (
        run_agent_loop(AgentContext(), _config(model), "执行", emit=events.append)
    )

    tools = [message for message in messages if message.role == "tool"]
    assert [message.tool_call_id for message in tools] == ["c1", "c2"]
    assert messages[-1].content == "完成"
    assert len([event for event in events if event.type == EventType.TOOL_EXECUTION_END]) == 2


async def test_recursion_limit_raises_before_executing_final_tool_batch():
    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo x"}, "id": "c1"}]},
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo y"}, "id": "c2"}]},
        ]
    )

    with pytest.raises(RecursionLimitError):
        await (
            run_agent_loop(
                AgentContext(), _config(model), "循环", recursion_limit=2
            )
        )


async def test_before_tool_call_blocks_without_side_effect():
    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo blocked"}, "id": "c1"}]},
            {"content": "已拒绝"},
        ]
    )

    async def before_tool_call(call, _context):
        return ToolDecision.block("测试拒绝")

    events: list = []
    messages = await (
        run_agent_loop(
            AgentContext(),
            _config(model, before_tool_call=before_tool_call),
            "执行",
            emit=events.append,
        )
    )

    result = next(event.payload for event in events if event.type == EventType.TOOL_EXECUTION_END)
    assert result.rejected is True
    assert "测试拒绝" in result.content
    assert messages[-1].content == "已拒绝"


async def test_continue_does_not_duplicate_user_message():
    from codeagent.core import run_agent_loop_continue

    context = AgentContext(messages=[
        __import__("codeagent.core", fromlist=["Message"]).Message(role="user", content="已有问题")
    ])
    messages = await (
        run_agent_loop_continue(
            context, _config(FakeClient(response="继续"))
        )
    )

    assert [message.role for message in messages] == ["assistant"]
    assert messages[0].content == "继续"


async def test_runtime_timeout_is_a_structured_tool_result():
    class SlowTool:
        name = "slow"
        description = "slow"
        parameters = {"type": "object"}

        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            await asyncio.Event().wait()
            return "late"

    from codeagent.core.ports import AgentTool

    assert isinstance(SlowTool(), AgentTool)
    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "slow", "args": {}, "id": "c1"}]},
            {"content": "超时"},
        ]
    )
    events: list = []
    config = AgentLoopConfig(
        model=ChatModelPort(model),
        tools=[SlowTool()],
        tool_runtime=ToolExecutionRuntime(max_concurrency=1),
        tool_timeout=0.001,
    )
    await (run_agent_loop(AgentContext(), config, "执行", emit=events.append))
    result = next(event.payload for event in events if event.type == EventType.TOOL_EXECUTION_END)
    assert result.status == "timed_out"
