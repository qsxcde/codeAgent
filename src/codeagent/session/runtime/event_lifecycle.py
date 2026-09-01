"""Event mapping and phase transitions for the session runtime."""

from __future__ import annotations

from dataclasses import replace

from codeagent.core.contracts.events import (
    SUBAGENT_EVENT_TYPES,
    AgentEvent,
    EventType,
)
from codeagent.session.runtime.event_mapper import EventMapper
from codeagent.session.runtime.state import RunPhase


class RuntimeEventMixin:
    """Translate core events and advance the runtime state machine."""

    def _handle_event(self, event: AgentEvent, run_id: str) -> None:
        if self._state.phase is RunPhase.IDLE or self._state.run_id != run_id:
            return
        for item in EventMapper.map_agent_event(event):
            is_subagent_event = self._is_correlated_subagent_event(item, run_id)
            if item.run_id is not None and item.run_id != run_id and not is_subagent_event:
                continue
            metadata = dict(item.metadata or {})
            metadata.setdefault("run_id", item.run_id or run_id)
            if is_subagent_event and item.parent_sequence is None:
                parent_sequence = self._state.next_sequence()
                metadata["parent_sequence"] = parent_sequence
                item = replace(item, parent_sequence=parent_sequence)
            item = replace(item, metadata=metadata, run_id=item.run_id or run_id)
            if is_subagent_event:
                if self._event_handler is not None:
                    self._event_handler(item, run_id)
                continue
            self.observe_event(item)
            metadata = dict(item.metadata or {})
            metadata.setdefault("phase", self.phase.value)
            metadata["sequence"] = self._state.next_sequence()
            item = replace(item, metadata=metadata, phase=self.phase.value)
            if item.type in {EventType.ERROR, EventType.ABORTED}:
                continue
            if self._event_handler is not None:
                self._event_handler(item, run_id)

    @staticmethod
    def _is_correlated_subagent_event(event: AgentEvent, parent_run_id: str) -> bool:
        if event.type not in SUBAGENT_EVENT_TYPES:
            return False
        metadata = dict(event.metadata or {})
        linked_parent = event.parent_run_id or metadata.get("parent_run_id")
        return str(linked_parent or "") == str(parent_run_id)

    @staticmethod
    def _map_agent_event(event: AgentEvent) -> list[AgentEvent]:
        return EventMapper.map_agent_event(event)

    def observe_event(self, event: AgentEvent) -> None:
        self._side_effects.observe(event)
        self._advance_phase(event)

    def _advance_phase(self, event: AgentEvent) -> None:
        target: RunPhase | None = None
        if event.type == EventType.MESSAGE_START:
            target = RunPhase.MODEL_WAIT
        elif event.type in {EventType.TOOL_EXECUTION_START, EventType.TOOL_STARTED}:
            target = RunPhase.TOOL_RUNNING
        elif event.type == EventType.CONFIRMATION_REQUESTED:
            target = RunPhase.AWAITING_CONFIRMATION
        elif event.type == EventType.ERROR:
            target = RunPhase.FAILED
        elif event.type == EventType.ABORTED:
            target = RunPhase.CANCELLED
        elif event.type == EventType.TURN_END and (event.metadata or {}).get("tool_results"):
            target = RunPhase.CONTINUING
        if target is None or self._state.phase is RunPhase.IDLE:
            return
        try:
            self._state.transition(target)
        except ValueError:
            if self._state.phase in {
                RunPhase.COMPLETED,
                RunPhase.FAILED,
                RunPhase.CANCELLED,
                RunPhase.FINALIZING,
            }:
                return
            raise


__all__ = ["RuntimeEventMixin"]
