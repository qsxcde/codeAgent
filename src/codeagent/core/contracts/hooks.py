"""Provider-neutral lifecycle observation Hook contracts."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from codeagent.core.contracts.events import AgentEvent, EventType

HookScope = Literal["turn", "model", "tool", "session"]
HookPhase = Literal["started", "updated", "finished"]
HookFailureStage = Literal["snapshot", "invoke", "await"]
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


@dataclass(frozen=True)
class HookDiagnostic:
    """Structured, non-persistent description of an isolated Hook failure."""

    hook_name: str
    stage: HookFailureStage
    event_type: str
    scope: HookScope | None
    phase: HookPhase | None
    run_id: str | None
    session_id: str | None
    error_type: str
    message: str
    code: str = "hook_failed"

    def as_metadata(self) -> dict[str, Any]:
        """Return a JSON-safe representation for diagnostics consumers."""
        return {
            "code": self.code,
            "hook_name": self.hook_name,
            "stage": self.stage,
            "event_type": self.event_type,
            "scope": self.scope,
            "phase": self.phase,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "error_type": self.error_type,
            "message": self.message,
        }


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


def core_event_scope_phase(event_type: str) -> tuple[HookScope, HookPhase] | None:
    """Return the core Hook scope and phase without constructing a snapshot."""
    return _CORE_EVENT_PHASES.get(event_type)


def hook_name(hook: LifecycleHook | None) -> str:
    """Return a stable callable identity without evaluating its repr."""
    if hook is None:
        return "event_snapshot"
    try:
        target = getattr(hook, "__func__", hook)
        module = getattr(target, "__module__", type(target).__module__)
        qualified_name = getattr(target, "__qualname__", type(target).__qualname__)
        return f"{module}.{qualified_name}"
    except Exception:  # noqa: BLE001 - diagnostic construction must not fail
        return "unknown_hook"


def make_hook_diagnostic(
    event: AgentEvent,
    exception: Exception,
    *,
    stage: HookFailureStage,
    hook: LifecycleHook | None = None,
    scope: HookScope | None = None,
    phase: HookPhase | None = None,
) -> HookDiagnostic:
    """Create a safe diagnostic from an event and an isolated Hook failure."""
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    run_id = event.run_id or metadata.get("run_id")
    session_id = event.session_id or metadata.get("session_id")
    try:
        message = str(exception) or type(exception).__name__
    except Exception:  # noqa: BLE001 - diagnostic construction must not fail
        message = type(exception).__name__
    return HookDiagnostic(
        hook_name=hook_name(hook),
        stage=stage,
        event_type=event.type,
        scope=scope,
        phase=phase,
        run_id=run_id,
        session_id=session_id,
        error_type=type(exception).__name__,
        message=message,
    )


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
    phase = session_event_phase(event)
    return to_lifecycle_hook_event(
        event,
        scope="session",
        phase=phase,
        session_id=event.session_id or (event.metadata or {}).get("session_id"),
    )


def session_event_phase(event: AgentEvent) -> HookPhase:
    """Classify a session event's phase without copying its payload."""
    metadata = event.metadata or {}
    if event.type == EventType.SESSION_STARTED:
        return "started"
    if event.type in {EventType.ERROR, EventType.RUN_CANCELLED} or (
        event.type == EventType.TURN_END and metadata.get("run_outcome")
    ):
        return "finished"
    return "updated"


__all__ = [
    "HookDiagnostic",
    "HookFailureStage",
    "HookPhase",
    "HookScope",
    "LifecycleHook",
    "LifecycleHookEvent",
    "classify_core_event",
    "classify_session_event",
    "core_event_scope_phase",
    "hook_name",
    "make_hook_diagnostic",
    "session_event_phase",
    "to_lifecycle_hook_event",
]
