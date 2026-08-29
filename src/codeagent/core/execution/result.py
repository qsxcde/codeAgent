"""Normalize strict tool outputs into the public core result shape."""

from __future__ import annotations

from typing import Any

from codeagent.core.execution.cleanup import CleanupResult
from codeagent.core.execution.state import ToolOperation
from codeagent.core.contracts.messages import (
    CleanupStatus,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
)

__all__ = ["normalize_tool_result"]


def normalize_tool_result(
    call: ToolCall,
    tool_name: str,
    operation: ToolOperation,
    output: Any,
) -> tuple[ToolResult, CleanupResult]:
    """Preserve a tool result while applying runtime cleanup semantics."""
    cleanup_confirmed = getattr(output, "cleanup_confirmed", True)
    cleanup_status = _clean_status(getattr(output, "cleanup_status", ""))
    cleanup_confirmed = _resolve_cleanup(cleanup_confirmed, cleanup_status)
    content = str(getattr(output, "content", output))
    status = getattr(output, "status", None)
    exit_code = getattr(output, "exit_code", None)
    duration_ms = int(getattr(output, "duration_ms", 0) or 0)
    truncated = bool(getattr(output, "output_truncated", False))
    semantic_success = getattr(output, "success", None)

    if status and status not in (ToolExecutionStatus.OK, "completed"):
        return _failed_result(
            call,
            tool_name,
            operation,
            content,
            status,
            cleanup_confirmed,
            cleanup_status,
            exit_code,
            duration_ms,
            truncated,
            semantic_success,
        )

    operation.status = ToolExecutionStatus.OK
    operation.cleanup_confirmed = True if cleanup_confirmed is None else cleanup_confirmed
    operation.cleanup_status = cleanup_status or _default_cleanup(cleanup_confirmed)
    if operation.cleanup_confirmed is False:
        operation.status = ToolExecutionStatus.CLEANUP_UNCERTAIN
    result = ToolResult(
        call.id,
        content,
        error=operation.cleanup_confirmed is False,
        name=tool_name,
        status=operation.status,
        operation_id=operation.operation_id,
        cleanup_confirmed=operation.cleanup_confirmed,
        cleanup_status=operation.cleanup_status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        output_truncated=truncated,
        semantic_success=semantic_success,
    )
    return result, CleanupResult(operation.cleanup_status)


def _clean_status(status: Any) -> str:
    return "" if status == CleanupStatus.NOT_REQUIRED else str(status or "")


def _resolve_cleanup(value: Any, status: str) -> bool | None:
    if status in {
        CleanupStatus.FAILED,
        CleanupStatus.UNCERTAIN,
        CleanupStatus.UNSUPPORTED,
    }:
        return False
    if status == CleanupStatus.CONFIRMED:
        return True
    return value


def _default_cleanup(cleanup_confirmed: bool | None) -> str:
    return (
        CleanupStatus.UNCERTAIN
        if cleanup_confirmed is False
        else CleanupStatus.CONFIRMED
    )


def _failed_result(
    call: ToolCall,
    tool_name: str,
    operation: ToolOperation,
    content: str,
    status: Any,
    cleanup_confirmed: bool | None,
    cleanup_status: str,
    exit_code: Any,
    duration_ms: int,
    truncated: bool,
    semantic_success: Any,
) -> tuple[ToolResult, CleanupResult]:
    operation.status = str(status)
    operation.cleanup_confirmed = False if cleanup_confirmed is False else cleanup_confirmed
    operation.cleanup_status = cleanup_status or _default_cleanup(cleanup_confirmed)
    cleanup = CleanupResult(operation.cleanup_status)
    return ToolResult(
        call.id,
        content,
        error=True,
        name=tool_name,
        status=operation.status,
        operation_id=operation.operation_id,
        cleanup_confirmed=cleanup_confirmed,
        cleanup_status=operation.cleanup_status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        output_truncated=truncated,
        semantic_success=semantic_success,
    ), cleanup
