from __future__ import annotations

import asyncio

import pytest

from codeagent.core.context import AgentContext
from codeagent.core.errors import AgentContinueError
from codeagent.core.ports import AgentLoopConfig, AgentTool, ToolDecision
from codeagent.core.messages import Message


class _Tool:
    name = "read"
    description = "Read a file"
    parameters = {"type": "object"}

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        return {"tool_call_id": tool_call_id, "arguments": arguments}


def test_agent_context_copy_isolated_from_original_lists() -> None:
    message = Message(role="user", content="hello")
    tool = _Tool()
    context = AgentContext(messages=[message], tools=[tool])

    copied = context.copy()
    copied.messages.append(Message(role="assistant", content="ok"))
    copied.tools.clear()

    assert len(context.messages) == 1
    assert context.tools == [tool]


def test_agent_loop_config_accepts_tools_and_context_hooks() -> None:
    async def transform(messages):
        return messages

    async def before(call, context):
        return ToolDecision.allow()

    async def after(call, result, context):
        return result

    config = AgentLoopConfig(
        model=object(),
        tools=[_Tool()],
        transform_context=transform,
        before_tool_call=before,
        after_tool_call=after,
    )

    assert isinstance(config.tools[0], AgentTool)
    assert asyncio.run(config.transform_context([])) == []
    assert asyncio.run(config.before_tool_call(None, None)).action == "allow"


def test_context_continue_rejects_empty_or_assistant_tail() -> None:
    with pytest.raises(AgentContinueError):
        AgentContext().validate_continue()

    with pytest.raises(AgentContinueError):
        AgentContext(messages=[Message(role="assistant", content="done")]).validate_continue()

    AgentContext(messages=[Message(role="user", content="retry")]).validate_continue()
