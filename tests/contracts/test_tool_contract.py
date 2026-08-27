"""AtomicTool and AgentTool execution contracts."""

from __future__ import annotations

import asyncio

import pytest

from codeagent.core.execution import ToolExecutionRuntime
from codeagent.core.messages import ToolCall, ToolExecutionStatus, ToolResult
from codeagent.tools.atomic import ReadTool


class EchoAgentTool:
    name = "echo"
    description = "echo"
    parameters = {"type": "object"}

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        return ToolResult(tool_call_id, arguments["text"], name=self.name)


async def test_atomic_tool_contract_returns_structured_result(tmp_path):
    path = tmp_path / "message.txt"
    path.write_text("hello", encoding="utf-8")

    result = await ToolExecutionRuntime().execute(
        ReadTool(), ToolCall("read-1", "read", {"file_path": str(path)})
    )

    assert result.error is False
    assert "hello" in result.content
    assert result.status == ToolExecutionStatus.OK


async def test_agent_tool_contract_preserves_operation_id():
    result = await ToolExecutionRuntime().execute(
        EchoAgentTool(),
        ToolCall("echo-1", "echo", {"text": "hello"}),
        operation_id="operation-1",
    )

    assert result.content == "hello"
    assert result.operation_id == "operation-1"
    assert result.cleanup_confirmed is True


async def test_tool_contract_cancellation_clears_active_operation():
    started = asyncio.Event()

    class BlockingTool(EchoAgentTool):
        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            started.set()
            await asyncio.Event().wait()

    runtime = ToolExecutionRuntime()
    task = asyncio.create_task(
        runtime.execute(BlockingTool(), ToolCall("block-1", "echo", {}), operation_id="op-1")
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.active_operations == {}
