from __future__ import annotations

import asyncio
import time

import pytest

from codeagent.core.execution.runtime import ToolExecutionRuntime
from codeagent.core.contracts.messages import ToolCall, ToolExecutionStatus, ToolResult


class _AgentTool:
    name = "echo"
    description = "echo"
    parameters = {"type": "object"}

    def __init__(self):
        self.calls = []

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        self.calls.append((tool_call_id, arguments, signal, on_update))
        return ToolResult(tool_call_id, arguments["text"], name=self.name)


async def test_runtime_executes_agent_tool_protocol_and_preserves_operation_id() -> None:
    tool = _AgentTool()
    call = ToolCall("c1", "echo", {"text": "hello"})

    result = await (
        ToolExecutionRuntime().execute(tool, call, operation_id="op-1")
    )

    assert result.content == "hello"
    assert result.operation_id == "op-1"
    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.cleanup_status == "confirmed"
    assert tool.calls[0][0:2] == ("c1", {"text": "hello"})


async def test_runtime_rejects_unadapted_legacy_tool_without_invoking_it() -> None:
    class LegacyTool:
        name = "legacy"
        Args = dict

        def __init__(self) -> None:
            self.invoked = False

        def invoke(self, _args: dict[str, str]) -> str:
            self.invoked = True
            return "must not run"

    tool = LegacyTool()
    result = await ToolExecutionRuntime().execute(
        tool, ToolCall("legacy-1", "legacy", {})
    )

    assert result.error is True
    assert result.status == ToolExecutionStatus.FAILED
    assert "工具契约" in result.content
    assert tool.invoked is False


async def test_runtime_reports_failed_cleanup_without_claiming_confirmation() -> None:
    started = asyncio.Event()

    class FailingCleanupTool(_AgentTool):
        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            started.set()
            await asyncio.Event().wait()

        async def cleanup(self, operation_id):
            raise RuntimeError("cleanup failed")

    runtime = ToolExecutionRuntime()
    task = asyncio.create_task(
        runtime.execute(
            FailingCleanupTool(),
            ToolCall("c1", "echo", {}),
            timeout=0.01,
            operation_id="op-1",
        )
    )
    await started.wait()

    result = await task

    assert result.status == ToolExecutionStatus.TIMED_OUT
    assert result.cleanup_confirmed is False
    assert result.cleanup_status == "failed"
    assert result.cleanup_uncertain is True


async def test_runtime_treats_false_cleanup_hook_result_as_failed_cleanup() -> None:
    started = asyncio.Event()

    class FalseCleanupTool(_AgentTool):
        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            started.set()
            await asyncio.Event().wait()

        async def cleanup(self, operation_id):
            return False

    runtime = ToolExecutionRuntime()
    task = asyncio.create_task(
        runtime.execute(
            FalseCleanupTool(),
            ToolCall("c1", "echo", {}),
            timeout=0.01,
            operation_id="op-1",
        )
    )
    await started.wait()
    result = await task

    assert result.status == ToolExecutionStatus.TIMED_OUT
    assert result.cleanup_confirmed is False
    assert result.cleanup_status == "failed"
    assert result.cleanup_uncertain is True


async def test_runtime_marks_sync_thread_timeout_as_unsupported_cleanup() -> None:
    from codeagent.app.composition.tools.adapter import adapt_tools

    started = asyncio.Event()

    class BlockingSyncTool:
        name = "sync"
        Args = dict

        def invoke(self, args):
            started.set()
            time.sleep(0.05)
            return "done"

    runtime = ToolExecutionRuntime()
    result_task = asyncio.create_task(
        runtime.execute(
            adapt_tools([BlockingSyncTool()])[0],
            ToolCall("c1", "sync", {}),
            timeout=0.001,
            operation_id="op-1",
        )
    )
    await started.wait()

    result = await result_task

    assert result.status == ToolExecutionStatus.TIMED_OUT
    assert result.cleanup_confirmed is False
    assert result.cleanup_status == "unsupported"
    assert result.cleanup_uncertain is True


async def test_cancel_all_waits_for_async_operation_cleanup_and_is_idempotent():
    started = asyncio.Event()
    cleaned = asyncio.Event()

    class CancellableTool(_AgentTool):
        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

    runtime = ToolExecutionRuntime()
    task = asyncio.create_task(
        runtime.execute(CancellableTool(), ToolCall("c1", "echo", {}), operation_id="op-1")
    )
    await started.wait()

    await runtime.cancel_all()
    await runtime.cancel_all()

    assert cleaned.is_set()
    assert runtime.active_operations == {}
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_runtime_honors_explicit_cleanup_status_from_tool_result():
    class ReportedUncertainTool(_AgentTool):
        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            return ToolResult(
                tool_call_id,
                "后台状态未知",
                name=self.name,
                error=True,
                status=ToolExecutionStatus.TIMED_OUT,
                cleanup_status="unsupported",
            )

    result = await ToolExecutionRuntime().execute(
        ReportedUncertainTool(), ToolCall("c1", "echo", {}), operation_id="op-1"
    )

    assert result.status == ToolExecutionStatus.TIMED_OUT
    assert result.cleanup_confirmed is False
    assert result.cleanup_status == "unsupported"
    assert result.cleanup_uncertain is True


async def test_successful_tool_keeps_completed_status_when_cleanup_is_uncertain():
    class SuccessfulUncertainTool(_AgentTool):
        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            return ToolResult(
                tool_call_id,
                "done",
                name=self.name,
                status=ToolExecutionStatus.OK,
                cleanup_status="unsupported",
            )

    result = await ToolExecutionRuntime().execute(
        SuccessfulUncertainTool(), ToolCall("c1", "echo", {}), operation_id="op-1"
    )

    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.cleanup_status == "unsupported"
    assert result.cleanup_uncertain is True
