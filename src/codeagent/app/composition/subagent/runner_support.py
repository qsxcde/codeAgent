"""Cleanup, result and diagnostic helpers for the serial Subagent runner."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from codeagent.core.contracts.subagents import (
    SubagentFailure,
    SubagentFailurePhase,
    SubagentReasonCode,
    SubagentResult,
    SubagentStatus,
)

_MAX_DIAGNOSTIC_CHARS = 2_000


async def observe_event(result: Any, active: Any) -> None:
    try:
        await result
    except Exception as exc:  # noqa: BLE001 - observers are isolated
        active.diagnostics.append(diagnostic("子事件回调", exc))


async def cancel_session(active: Any) -> None:
    session = active.session
    if session is not None:
        cancel_and_wait = getattr(session, "cancel_and_wait", None)
        if callable(cancel_and_wait):
            result = cancel_and_wait()
            if inspect.isawaitable(result):
                await result
            return
        abort = getattr(session, "abort", None)
        if callable(abort):
            abort()
    task = active.task
    if task is not None and not task.done() and task is not asyncio.current_task():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def close_active(active: Any) -> None:
    if active.unsubscribe is not None:
        try:
            active.unsubscribe()
        except Exception as exc:  # noqa: BLE001 - cleanup is best effort
            active.diagnostics.append(diagnostic("取消子事件订阅", exc))
    if active.event_tasks:
        await asyncio.gather(*active.event_tasks, return_exceptions=True)
    close = getattr(active.session, "close", None)
    if callable(close):
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 - preserve primary outcome
            active.diagnostics.append(diagnostic("关闭子 Session", exc))


def child_run_id(session: Any) -> str | None:
    value = getattr(session, "active_run_id", None)
    if value:
        return str(value)
    outcome = getattr(session, "last_outcome", None)
    value = getattr(outcome, "run_id", None)
    return str(value) if value else None


def child_summary(session: Any, returned: Any) -> str:
    if isinstance(returned, str):
        return bounded(returned)
    history = getattr(session, "history", ())
    for message in reversed(list(history or ())):
        if getattr(message, "role", None) == "assistant":
            return bounded(str(getattr(message, "content", "") or ""))
    return bounded(str(returned or ""))


def child_outcome(session: Any) -> tuple[str | None, str | None]:
    """Read a Session outcome without importing Session into the runner."""
    outcome = getattr(session, "last_outcome", None)
    phase = getattr(outcome, "phase", None)
    phase_value = getattr(phase, "value", phase)
    if phase_value is None:
        return None, None
    failure = getattr(session, "last_failure", None)
    if isinstance(failure, dict):
        message = failure.get("error") or failure.get("error_message")
    else:
        message = None
    return str(phase_value), str(message) if message else None


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


def diagnostic(prefix: str, error: Exception) -> str:
    return bounded(f"{prefix}: {error}")


def bounded(value: str, limit: int = _MAX_DIAGNOSTIC_CHARS) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


__all__ = [
    "bounded",
    "cancel_session",
    "cancelled_result",
    "child_run_id",
    "child_outcome",
    "child_summary",
    "close_active",
    "diagnostic",
    "failure_result",
    "observe_event",
    "rejected_result",
]
