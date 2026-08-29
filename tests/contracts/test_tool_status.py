from __future__ import annotations

import pytest

from codeagent.core.contracts.messages import CleanupStatus, ToolExecutionStatus, ToolResult
from codeagent.core.contracts.tool_status import ToolLifecycleStatus, ToolStatusSnapshot


def test_tool_status_snapshot_normalizes_legacy_execution_values() -> None:
    snapshot = ToolStatusSnapshot(
        tool_call_id="call-1",
        operation_id="op-1",
        tool_name="bash",
        status=ToolExecutionStatus.OK,
        cleanup_status=CleanupStatus.CONFIRMED,
        elapsed_ms=120,
    )

    assert snapshot.status == ToolLifecycleStatus.COMPLETED
    assert snapshot.is_terminal is True
    assert snapshot.to_dict() == {
        "tool_call_id": "call-1",
        "operation_id": "op-1",
        "tool_name": "bash",
        "status": "completed",
        "cleanup_status": "confirmed",
        "elapsed_ms": 120,
        "error_code": None,
        "queue_position": None,
    }


def test_tool_status_snapshot_keeps_cleanup_independent_from_cancelled_status() -> None:
    snapshot = ToolStatusSnapshot(
        tool_call_id="call-2",
        tool_name="bash",
        status=ToolLifecycleStatus.CANCELLED,
        cleanup_status=CleanupStatus.UNCERTAIN,
    )

    assert snapshot.status == ToolLifecycleStatus.CANCELLED
    assert snapshot.cleanup_status == CleanupStatus.UNCERTAIN
    assert snapshot.is_terminal is True


def test_tool_status_snapshot_rejects_unknown_state_and_negative_elapsed() -> None:
    with pytest.raises(ValueError, match="unsupported tool lifecycle status"):
        ToolStatusSnapshot(tool_call_id="call-3", status="finished")

    with pytest.raises(ValueError, match="elapsed_ms"):
        ToolStatusSnapshot(tool_call_id="call-3", elapsed_ms=-1)


def test_tool_result_uses_completed_for_new_successes_but_reads_legacy_ok() -> None:
    assert ToolResult("call-4", "done").status == ToolLifecycleStatus.COMPLETED
    assert (
        ToolResult("call-5", "done", status=ToolExecutionStatus.OK).status
        == ToolLifecycleStatus.COMPLETED
    )
