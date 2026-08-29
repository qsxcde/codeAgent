"""Provider-neutral lifecycle observation Hook contracts."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from codeagent.core.contracts.events import AgentEvent, EventType

HookScope = Literal["turn", "model", "tool", "session"]
HookPhase = Literal["started", "updated", "finished"]
LifecycleHook = Callable[["LifecycleHookEvent"], Any]


@dataclass(frozen=True)
class LifecycleHookEvent:
    """Detached, provider-neutral snapshot delivered to an observation Hook."""

    scope: HookScope
    phase: HookPhase
    event: AgentEvent
    run_id: str | None = None
    session_id: str | None = None

    @property
    def payload(self) -> Any:
        """Expose the detached payload without duplicating the event contract."""
        return self.event.payload

    @property
    def event_type(self) -> str:
        """Return the underlying structured event type."""
        return self.event.type


_CORE_EVENT_PHASES: dict[str, tuple[HookScope, HookPhase]] = {
    EventType.TURN_START: ("turn", "started"),
    EventType.TURN_END: ("turn", "finished"),
    EventType.MODEL_REQUEST_STARTED: ("model", "started"),
    EventType.MODEL_REQUEST_FINISHED: ("model", "finished"),
    EventType.MESSAGE_UPDATE: ("model", "updated"),
    EventType.CONTEXT_BUDGET: ("model", "updated"),
    EventType.CONTEXT_PREFLIGHT: ("model", "updated"),
    EventType.USAGE: ("model", "updated"),
    EventType.TOOL_EXECUTION_QUEUED: ("tool", "updated"),
    EventType.TOOL_EXECUTION_START: ("tool", "started"),
    EventType.TOOL_EXECUTION_UPDATE: ("tool", "updated"),
    EventType.TOOL_EXECUTION_END: ("tool", "finished"),
}


def to_lifecycle_hook_event(
    event: AgentEvent,
    *,
    scope: HookScope,
    phase: HookPhase,
    session_id: str | None = None,
) -> LifecycleHookEvent:
    """Build a detached Hook event while preserving correlation metadata."""
    snapshot = copy.deepcopy(event)
    metadata = dict(snapshot.metadata or {})
    run_id = snapshot.run_id or metadata.get("run_id")
    resolved_session_id = snapshot.session_id or session_id or metadata.get("session_id")
    if run_id is not None:
        metadata.setdefault("run_id", run_id)
    if resolved_session_id is not None:
        metadata.setdefault("session_id", resolved_session_id)
    snapshot = replace(
        snapshot,
        metadata=metadata,
        run_id=run_id,
        session_id=resolved_session_id,
    )
    return LifecycleHookEvent(
        scope=scope,
        phase=phase,
        event=snapshot,
        run_id=run_id,
        session_id=resolved_session_id,
    )


def classify_core_event(event: AgentEvent) -> LifecycleHookEvent | None:
    """Classify one core event for lifecycle observation, if applicable."""
    lifecycle = _CORE_EVENT_PHASES.get(event.type)
    if lifecycle is None:
        return None
    scope, phase = lifecycle
    return to_lifecycle_hook_event(event, scope=scope, phase=phase)


def classify_session_event(event: AgentEvent) -> LifecycleHookEvent:
    """Classify one session event as a session lifecycle observation."""
    metadata = event.metadata or {}
    if event.type == EventType.SESSION_STARTED:
        phase: HookPhase = "started"
    elif event.type in {EventType.ERROR, EventType.RUN_CANCELLED} or (
        event.type == EventType.TURN_END and metadata.get("run_outcome")
    ):
        phase = "finished"
    else:
        phase = "updated"
    return to_lifecycle_hook_event(
        event,
        scope="session",
        phase=phase,
        session_id=event.session_id or metadata.get("session_id"),
    )


__all__ = [
    "HookPhase",
    "HookScope",
    "LifecycleHook",
    "LifecycleHookEvent",
    "classify_core_event",
    "classify_session_event",
    "to_lifecycle_hook_event",
]
