"""Build bounded, correlated events for one Subagent delegation."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.subagents import SubagentResult, SubagentStatus

from .runner_support import bounded, record_diagnostic

_MAX_EVENT_DETAIL_CHARS = 512
_MAX_TASK_LABEL_CHARS = 96


def make_queued_event(active: Any) -> AgentEvent:
    """Describe admission to the runner before a child run exists."""
    return _make_event(active, EventType.SUBAGENT_QUEUED, SubagentStatus.QUEUED)


def make_started_event(active: Any) -> AgentEvent:
    """Describe creation of the isolated child execution boundary."""
    return _make_event(active, EventType.SUBAGENT_STARTED, SubagentStatus.RUNNING)


def make_progress_event(active: Any, child_event: AgentEvent) -> AgentEvent:
    """Project one child event into a bounded parent-facing summary."""
    status = _status_for_child_event(active, child_event)
    phase = _phase_for_child_event(child_event)
    payload = _progress_payload(child_event, phase)
    return _make_event(
        active,
        EventType.SUBAGENT_PROGRESS,
        status,
        child_event=child_event,
        child_phase=phase,
        payload=payload,
    )


def make_finished_event(active: Any, result: SubagentResult) -> AgentEvent:
    """Build the single bounded terminal event for a delegation."""
    return _make_event(
        active,
        EventType.SUBAGENT_FINISHED,
        result.status,
        child_phase=result.failure.phase if result.failure is not None else "completed",
        payload=result.to_dict(),
        result=result,
    )


async def publish_event(callback: Any, event: AgentEvent, active: Any) -> None:
    """Invoke an event sink without allowing observer failures to alter execution."""
    if callback is None:
        return
    try:
        result = callback(event)
        if inspect.isawaitable(result):
            await result
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - observer failures are diagnostics
        record_diagnostic(active, f"子事件回调: {bounded(str(exc))}")


def _make_event(
    active: Any,
    event_type: str,
    status: SubagentStatus,
    *,
    child_event: AgentEvent | None = None,
    child_phase: str | None = None,
    payload: dict[str, Any] | None = None,
    result: SubagentResult | None = None,
) -> AgentEvent:
    child_run_id = _child_run_id(active, child_event, result)
    child_sequence = _child_sequence(active, child_event)
    metadata: dict[str, Any] = {
        "delegation_id": active.request.delegation_id,
        "parent_run_id": active.request.parent_run_id,
        "child_run_id": child_run_id,
        "attempt_id": active.attempt_id,
        "depth": active.request.depth,
        "profile": active.request.profile,
        "task_label": _task_label(active.request.task),
        "subagent_status": status.value,
        "status": status.value,
    }
    if child_phase:
        metadata["child_phase"] = child_phase
    if child_event is not None:
        metadata["child_event_type"] = child_event.type
    if child_sequence is not None:
        metadata["child_sequence"] = child_sequence
        if child_run_id is not None:
            # The child Session already assigned this sequence. The parent
            # runtime adds parent_sequence without overwriting it.
            metadata["sequence"] = child_sequence
    if result is not None:
        metadata["terminal"] = True
        metadata["cleanup_uncertain"] = result.cleanup_uncertain
        if result.failure is not None:
            metadata.update(
                {
                    "reason_code": result.failure.reason_code,
                    "error_code": result.failure.reason_code,
                    "cleanup_uncertain": result.failure.cleanup_uncertain
                    or result.cleanup_uncertain,
                }
            )
    session_id = _child_session_id(active, child_event)
    return AgentEvent(
        event_type,
        payload=payload,
        metadata=metadata,
        session_id=session_id,
        run_id=child_run_id or active.request.parent_run_id,
        delegation_id=active.request.delegation_id,
        parent_run_id=active.request.parent_run_id,
        child_run_id=child_run_id,
        attempt_id=active.attempt_id,
        depth=active.request.depth,
        subagent_status=status.value,
        status=status.value,
        child_phase=child_phase,
        child_event_type=child_event.type if child_event is not None else None,
        child_sequence=child_sequence,
        error_code=(result.failure.reason_code if result and result.failure else None),
        cleanup_uncertain=(result.cleanup_uncertain if result is not None else None),
    )


def _status_for_child_event(active: Any, event: AgentEvent) -> SubagentStatus:
    if event.type == EventType.CONFIRMATION_REQUESTED:
        return SubagentStatus.WAITING_CONFIRMATION
    if event.type in {EventType.CANCELLING, EventType.ABORTED}:
        return SubagentStatus.CANCELLING
    current = getattr(getattr(active, "state", None), "status", None)
    if current in {SubagentStatus.WAITING_CONFIRMATION, SubagentStatus.CANCELLING}:
        return current
    return SubagentStatus.RUNNING


def _phase_for_child_event(event: AgentEvent) -> str | None:
    if event.type == EventType.CONFIRMATION_REQUESTED:
        return "awaiting_confirmation"
    if event.type in {EventType.CANCELLING, EventType.ABORTED}:
        return "cancelling"
    phase = event.child_phase or event.phase
    if phase is not None:
        return str(getattr(phase, "value", phase))
    metadata = dict(event.metadata or {})
    value = metadata.get("phase")
    return str(value) if value is not None else None


def _progress_payload(event: AgentEvent, phase: str | None) -> dict[str, Any]:
    metadata = dict(event.metadata or {})
    payload = event.payload if isinstance(event.payload, dict) else {}
    details: dict[str, Any] = {"child_event_type": event.type}
    if phase:
        details["child_phase"] = phase
    for name in ("tool_call_id", "operation_id", "tool_name", "status", "elapsed_ms"):
        value = getattr(event, name, None)
        if value is None:
            value = metadata.get(name)
        if value is not None:
            details[name] = _safe_detail(value)
    if event.type == EventType.CONFIRMATION_REQUESTED:
        for name in ("request_id", "tool_call_id", "tool"):
            value = payload.get(name) or metadata.get(name)
            if value is not None:
                details[name] = _safe_detail(value)
        reason = payload.get("reason") or metadata.get("reason")
        if reason:
            details["reason"] = bounded(str(reason), _MAX_EVENT_DETAIL_CHARS)
    if event.type in {EventType.ERROR, EventType.ABORTED} and event.payload is not None:
        details["diagnostic"] = bounded(str(event.payload), _MAX_EVENT_DETAIL_CHARS)
    return details


def _child_run_id(
    active: Any,
    child_event: AgentEvent | None,
    result: SubagentResult | None,
) -> str | None:
    value = (
        getattr(child_event, "run_id", None)
        if child_event is not None
        else None
    ) or getattr(result, "child_run_id", None)
    return str(value) if value else getattr(active, "child_run_id", None)


def _child_session_id(active: Any, child_event: AgentEvent | None) -> str | None:
    if child_event is not None and child_event.session_id:
        return str(child_event.session_id)
    value = getattr(getattr(active, "session", None), "session_id", None)
    return str(value) if value else None


def _child_sequence(active: Any, child_event: AgentEvent | None) -> int | None:
    if child_event is not None:
        metadata = dict(child_event.metadata or {})
        value = child_event.child_sequence
        if value is None:
            value = metadata.get("child_sequence", metadata.get("sequence"))
        converted = _nonnegative_int(value)
        if converted is not None:
            active.child_sequence = converted
            return converted
    return _nonnegative_int(getattr(active, "child_sequence", None))


def _safe_detail(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return bounded(str(value), _MAX_EVENT_DETAIL_CHARS)


def _task_label(value: Any) -> str:
    """Keep one safe, bounded task label for parent-facing presentation."""
    first_line = str(value or "").splitlines()[0].strip()
    normalized = " ".join(first_line.split())
    if len(normalized) <= _MAX_TASK_LABEL_CHARS:
        return normalized
    return normalized[: _MAX_TASK_LABEL_CHARS - 1] + "…"


def _nonnegative_int(value: Any) -> int | None:
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return None
    return converted if converted >= 0 else None


__all__ = [
    "make_finished_event",
    "make_progress_event",
    "make_queued_event",
    "make_started_event",
    "publish_event",
]
