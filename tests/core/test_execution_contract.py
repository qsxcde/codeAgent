from __future__ import annotations

import asyncio

from codeagent.core.execution import ToolExecutionRuntime
from codeagent.core.messages import ToolCall, ToolExecutionStatus, ToolResult


class _AgentTool:
    name = "echo"
    description = "echo"
    parameters = {"type": "object"}

    def __init__(self):
        self.calls = []

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        self.calls.append((tool_call_id, arguments, signal, on_update))
        return ToolResult(tool_call_id, arguments["text"], name=self.name)


def test_runtime_executes_agent_tool_protocol_and_preserves_operation_id() -> None:
    tool = _AgentTool()
    call = ToolCall("c1", "echo", {"text": "hello"})

    result = asyncio.run(
        ToolExecutionRuntime().execute(tool, call, operation_id="op-1")
    )

    assert result.content == "hello"
    assert result.operation_id == "op-1"
    assert result.status == ToolExecutionStatus.OK
    assert tool.calls[0][0:2] == ("c1", {"text": "hello"})
