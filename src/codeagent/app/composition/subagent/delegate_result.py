"""Translate a Subagent result into the core ToolResult contract."""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.messages import ToolExecutionStatus, ToolResult
from codeagent.core.contracts.subagents import (
    SubagentReasonCode,
    SubagentResult,
    SubagentStatus,
)

_MAX_RESULT_CHARS = 8_000


def tool_result(tool_call_id: str, result: SubagentResult) -> ToolResult:
    """Keep status, failure and cleanup facts visible to the parent Agent."""
    details: dict[str, Any] = {
        "delegation_id": result.delegation_id,
        "child_run_id": result.child_run_id,
        "attempt_id": result.attempt_id,
        "subagent_status": result.status.value,
        "diagnostics": list(result.diagnostics),
    }
    if result.failure is not None:
        details.update(result.failure.as_metadata())
    cleanup_uncertain = bool(
        result.cleanup_uncertain
        or (result.failure is not None and result.failure.cleanup_uncertain)
    )
    details["cleanup_uncertain"] = cleanup_uncertain
    cleanup_confirmed = False if cleanup_uncertain else True
    cleanup_status = "uncertain" if cleanup_uncertain else "confirmed"

    if result.status is SubagentStatus.COMPLETED:
        return ToolResult(
            tool_call_id,
            bounded(result.summary),
            details=details,
            name="delegate",
            status=ToolExecutionStatus.COMPLETED,
            cleanup_confirmed=cleanup_confirmed,
            cleanup_status=cleanup_status,
        )

    failure = result.failure
    message = failure.message if failure is not None else "子 Agent 未完成"
    status = {
        SubagentStatus.REJECTED: ToolExecutionStatus.REJECTED,
        SubagentStatus.TIMED_OUT: ToolExecutionStatus.TIMED_OUT,
        SubagentStatus.CANCELLED: ToolExecutionStatus.CANCELLED,
    }.get(result.status, ToolExecutionStatus.FAILED)
    return ToolResult(
        tool_call_id,
        f"[子 Agent {result.status.value}] {bounded(message, 2_000)}",
        details=details,
        error=True,
        name="delegate",
        rejected=result.status is SubagentStatus.REJECTED,
        status=status,
        cleanup_confirmed=cleanup_confirmed,
        cleanup_status=cleanup_status,
    )


def error_result(
    tool_call_id: str,
    reason_code: str,
    message: str,
    *,
    status: str,
    rejected: bool = False,
) -> ToolResult:
    return ToolResult(
        tool_call_id,
        f"[委派被拒绝] {message}",
        details={"reason_code": reason_code, "error_message": message},
        error=True,
        name="delegate",
        rejected=rejected,
        status=status,
        cleanup_confirmed=True,
    )


def bounded(value: str, limit: int = _MAX_RESULT_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[子 Agent 摘要已截断]"


__all__ = ["bounded", "error_result", "tool_result"]
