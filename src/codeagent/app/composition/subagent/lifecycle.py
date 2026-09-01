"""Lifecycle guards shared by the serial Subagent runner."""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.errors import SubagentStateError
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.subagents import SubagentResult, SubagentStatus

from .runner_support import record_diagnostic


def mark_queued(active: Any) -> None:
    active.state.transition(SubagentStatus.QUEUED)


def mark_starting(active: Any) -> None:
    active.state.transition(
        SubagentStatus.STARTING,
        attempt_id=active.attempt_id,
    )


def mark_running(active: Any) -> None:
    active.state.transition(
        SubagentStatus.RUNNING,
        child_run_id=active.child_run_id,
        attempt_id=active.attempt_id,
    )


def observe_child_event(active: Any, event: AgentEvent) -> bool:
    """Update delegation state; return false when the event arrived too late."""
    if active.event_forwarding_closed or active.state.is_terminal:
        record_diagnostic(active, "忽略终态后的迟到子事件")
        return False
    child_run_id = getattr(event, "run_id", None)
    if child_run_id:
        active.child_run_id = str(child_run_id)
    _remember_child_sequence(active, event)
    target = _state_target(event)
    if target is None:
        return True
    if target is SubagentStatus.CANCELLING:
        if active.state.status in {
            SubagentStatus.STARTING,
            SubagentStatus.RUNNING,
            SubagentStatus.WAITING_CONFIRMATION,
        }:
            _transition(active, target)
        _remember_child_identity(active)
        return True
    if target is SubagentStatus.WAITING_CONFIRMATION:
        if active.state.status is SubagentStatus.RUNNING:
            _transition(active, target)
        _remember_child_identity(active)
        return True
    if active.state.status is SubagentStatus.WAITING_CONFIRMATION:
        _transition(active, SubagentStatus.RUNNING)
    elif active.state.status is SubagentStatus.STARTING:
        _transition(active, SubagentStatus.RUNNING)
    _remember_child_identity(active)
    return True


def commit_terminal(active: Any, result: SubagentResult) -> SubagentResult:
    """Commit one terminal result and make repeated commits observable only as diagnostics."""
    if active.state.is_terminal:
        existing = active.state.terminal_result
        if existing != result:
            record_diagnostic(active, "忽略冲突的重复子 Agent 终态")
        return existing or result

    if result.status in {SubagentStatus.CANCELLED, SubagentStatus.TIMED_OUT}:
        if active.state.status is SubagentStatus.QUEUED:
            _transition(active, result.status, result=result)
            return result
        if active.state.status is not SubagentStatus.CANCELLING:
            _transition(active, SubagentStatus.CANCELLING)
    elif result.status is SubagentStatus.FAILED and active.state.status is SubagentStatus.QUEUED:
        _transition(active, SubagentStatus.STARTING)
    try:
        active.state.finish(result)
    except SubagentStateError as exc:
        record_diagnostic(active, f"提交子 Agent 终态失败: {exc}")
    return result


def _state_target(event: AgentEvent) -> SubagentStatus | None:
    if event.type == EventType.CONFIRMATION_REQUESTED:
        return SubagentStatus.WAITING_CONFIRMATION
    if event.type in {EventType.CANCELLING, EventType.ABORTED}:
        return SubagentStatus.CANCELLING
    return SubagentStatus.RUNNING


def _transition(
    active: Any,
    target: SubagentStatus,
    *,
    result: SubagentResult | None = None,
) -> None:
    try:
        active.state.transition(
            target,
            result=result,
            child_run_id=active.child_run_id,
            attempt_id=active.attempt_id,
        )
    except SubagentStateError as exc:
        record_diagnostic(active, f"子 Agent 状态转换失败: {exc}")


def _remember_child_sequence(active: Any, event: AgentEvent) -> None:
    metadata = dict(event.metadata or {})
    value = event.child_sequence
    if value is None:
        value = metadata.get("child_sequence", metadata.get("sequence"))
    try:
        sequence = int(value)
    except (TypeError, ValueError):
        return
    if sequence >= 0:
        active.child_sequence = sequence


def _remember_child_identity(active: Any) -> None:
    """Capture a child run id without letting malformed callbacks escape."""
    if active.state.is_terminal:
        return
    _transition(active, active.state.status)


__all__ = [
    "commit_terminal",
    "mark_queued",
    "mark_running",
    "mark_starting",
    "observe_child_event",
]
