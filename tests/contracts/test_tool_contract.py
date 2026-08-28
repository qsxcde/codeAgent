"""AtomicTool and AgentTool execution contracts."""

from __future__ import annotations

import asyncio
import threading

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


async def test_sync_atomic_adapter_reports_uncertain_cleanup_on_cancellation():
    from codeagent.app.composition.tools.factory import adapt_tools
    from codeagent.tools.base import AtomicTool
    from pydantic import BaseModel

    class EmptyArgs(BaseModel):
        pass

    started = threading.Event()
    release = threading.Event()

    class BlockingAtomicTool(AtomicTool):
        name = "blocking"
        description = "blocking"
        Args = EmptyArgs

        def _invoke(self, _args):
            started.set()
            release.wait()
            return "late"

    adapted = adapt_tools([BlockingAtomicTool()])[0]
    assert adapted.supports_cancellation is False
    runtime = ToolExecutionRuntime()
    task = asyncio.create_task(
        runtime.execute(adapted, ToolCall("block-1", "blocking", {}), operation_id="op-1")
    )
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set(), task.exception() if task.done() else "tool did not start"
    task.cancel()

    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.cleanup_status == "unsupported"
        assert runtime.cleanup_uncertain is True
    finally:
        release.set()


async def test_atomic_adapter_preserves_structured_async_tool_result():
    from codeagent.app.composition.tools.factory import adapt_tools
    from codeagent.tools.atomic.bash import BashInvocationResult
    from codeagent.tools.base import AtomicTool
    from pydantic import BaseModel

    class EmptyArgs(BaseModel):
        pass

    class StructuredAtomicTool(AtomicTool):
        name = "structured"
        description = "structured"
        Args = EmptyArgs

        async def ainvoke(self, _args):
            return BashInvocationResult(
                "cleanup uncertain",
                status="cleanup_uncertain",
                cleanup_confirmed=False,
                success=False,
            )

    adapted = adapt_tools([StructuredAtomicTool()])[0]
    result = await ToolExecutionRuntime().execute(
        adapted, ToolCall("structured-1", "structured", {})
    )

    assert result.status == "cleanup_uncertain"
    assert result.cleanup_confirmed is False
    assert result.cleanup_uncertain is True
