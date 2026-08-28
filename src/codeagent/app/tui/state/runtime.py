"""TUI 运行态归约的对外入口。"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable

from codeagent.core.events import AgentEvent, EventType

from .runtime_state import RuntimePhase, RuntimeSnapshot, phase_label
from .runtime_transitions import transition

__all__ = [
    "RuntimePhase",
    "RuntimeSnapshot",
    "RuntimeReducer",
    "reduce_runtime_event",
    "phase_label",
]


class RuntimeReducer:
    """将 ``AgentEvent`` 归约为 ``RuntimeSnapshot``。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock

    def apply(self, snapshot: RuntimeSnapshot, event: AgentEvent) -> RuntimeSnapshot:
        """应用一个事件；明确过期的 session/run 事件保持原快照。"""
        metadata = dict(event.metadata or {})
        for field_name in (
            "session_id",
            "run_id",
            "tool_call_id",
            "operation_id",
            "phase",
            "elapsed_ms",
            "error_code",
            "retryable",
            "cleanup_uncertain",
            "side_effect_state",
        ):
            value = getattr(event, field_name, None)
            if value is not None:
                metadata.setdefault(field_name, value)
        session_id = event.session_id or metadata.get("session_id")
        run_id = event.run_id or metadata.get("run_id")
        if not self._belongs_to_snapshot(snapshot, session_id, run_id, event.type):
            return snapshot

        now = self._clock()
        current_session = str(session_id) if session_id is not None else snapshot.session_id
        current_run = str(run_id) if run_id is not None else snapshot.run_id
        next_snapshot = snapshot
        if current_session is not None and (
            snapshot.session_id is None
            or event.type in {EventType.SESSION_STARTED, EventType.RESTORE_STARTED}
        ):
            next_snapshot = replace(next_snapshot, session_id=current_session)
        if current_run is not None and (
            snapshot.run_id is None
            or event.type in {EventType.SESSION_STARTED, EventType.RESTORE_STARTED}
        ):
            next_snapshot = replace(next_snapshot, run_id=current_run)

        target = transition(next_snapshot, event, metadata)
        if target.phase != snapshot.phase:
            target = replace(target, phase_started_at=now, elapsed_ms=0)
        elif target.phase_started_at is not None:
            target = replace(target, elapsed_ms=max(0, round((now - target.phase_started_at) * 1000)))
        return replace(target, last_event_at=now)

    def _belongs_to_snapshot(
        self,
        snapshot: RuntimeSnapshot,
        session_id: Any,
        run_id: Any,
        event_type: str,
    ) -> bool:
        """旧事件不能覆盖当前界面；无上下文的旧事件保持兼容。"""
        if session_id is not None and snapshot.session_id is not None:
            if str(session_id) != snapshot.session_id and event_type not in {
                EventType.SESSION_STARTED,
                EventType.RESTORE_STARTED,
            }:
                return False
        if run_id is not None and snapshot.run_id is not None:
            if str(run_id) != snapshot.run_id:
                return event_type in {EventType.SESSION_STARTED, EventType.RESTORE_STARTED}
        return True


def reduce_runtime_event(
    snapshot: RuntimeSnapshot,
    event: AgentEvent,
    clock: Callable[[], float] = time.monotonic,
) -> RuntimeSnapshot:
    """函数式归约入口，方便组件和离线测试直接使用。"""
    return RuntimeReducer(clock).apply(snapshot, event)
