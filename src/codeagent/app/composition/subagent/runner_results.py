"""Terminal result constructors for the serial Subagent runner."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from codeagent.core.contracts.subagents import (
    SubagentFailure,
    SubagentFailurePhase,
    SubagentReasonCode,
    SubagentResult,
    SubagentStatus,
)

from .runner_support import bounded


def failure_result(
    active: Any,
    status: SubagentStatus,
    reason: SubagentReasonCode,
    phase: SubagentFailurePhase,
    error: Exception,
) -> SubagentResult:
    failure = SubagentFailure(
        reason_code=reason.value,
        message=bounded(str(error)),
        phase=phase.value,
    )
    return SubagentResult(
        delegation_id=active.request.delegation_id,
        status=status,
        child_run_id=active.child_run_id,
        attempt_id=active.attempt_id,
        failure=failure,
        diagnostics=tuple(active.diagnostics),
        cleanup_uncertain=bool(getattr(active, "cleanup_uncertain", False)),
    )


def rejected_result(request: Any, reason: str, message: str) -> SubagentResult:
    delegation_id = getattr(request, "delegation_id", "invalid") or "invalid"
    return SubagentResult(
        delegation_id=str(delegation_id),
        status=SubagentStatus.REJECTED,
        failure=SubagentFailure(
            reason_code=reason,
            message=bounded(message),
            phase=SubagentFailurePhase.VALIDATION.value,
        ),
    )


def cancelled_result(active: Any) -> SubagentResult:
    return failure_result(
        active,
        SubagentStatus.CANCELLED,
        SubagentReasonCode.PARENT_CANCELLED,
        SubagentFailurePhase.CANCELLING,
        RuntimeError("父 Agent 已取消子运行"),
    )


def timed_out_result(active: Any) -> SubagentResult:
    return failure_result(
        active,
        SubagentStatus.TIMED_OUT,
        SubagentReasonCode.TIMEOUT,
        SubagentFailurePhase.CANCELLING,
        RuntimeError("子 Agent 达到墙钟时间预算"),
    )


def budget_exceeded_result(active: Any) -> SubagentResult:
    detail = getattr(active, "budget_detail", None) or "子 Agent 达到执行预算"
    return failure_result(
        active,
        SubagentStatus.FAILED,
        SubagentReasonCode.BUDGET_EXCEEDED,
        SubagentFailurePhase.CANCELLING,
        RuntimeError(detail),
    )


def cancellation_result(active: Any) -> SubagentResult:
    """Map an active cancellation reason to its terminal Subagent result."""
    if getattr(active, "cancel_reason", None) is SubagentReasonCode.TIMEOUT:
        return timed_out_result(active)
    if getattr(active, "cancel_reason", None) is SubagentReasonCode.BUDGET_EXCEEDED:
        return budget_exceeded_result(active)
    return cancelled_result(active)


def finalize_result(result: SubagentResult, active: Any) -> SubagentResult:
    """Attach post-run cleanup facts after all cleanup work has finished."""
    diagnostics = tuple(active.diagnostics)
    if getattr(active, "cleanup_uncertain", False):
        failure = result.failure
        if failure is not None:
            failure = replace(failure, cleanup_uncertain=True)
        return replace(
            result,
            failure=failure,
            cleanup_uncertain=True,
            diagnostics=diagnostics,
        )
    return replace(result, diagnostics=diagnostics)


__all__ = [
    "budget_exceeded_result",
    "cancellation_result",
    "cancelled_result",
    "failure_result",
    "finalize_result",
    "rejected_result",
    "timed_out_result",
]
