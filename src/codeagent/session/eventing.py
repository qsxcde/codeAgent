"""Event correlation helpers for the session facade."""

from __future__ import annotations

from dataclasses import replace

from codeagent.core.contracts.events import AgentEvent


class SessionEventMixin:
    """Add session/run correlation before publishing an event."""

    def _on_run_event(self, event: AgentEvent, run_id: str) -> None:
        self._emit(event, run_id)

    def _emit(self, event: AgentEvent, run_id: str | None) -> None:
        metadata = dict(event.metadata or {})
        metadata.setdefault("session_id", self._session_id)
        if run_id is not None:
            metadata.setdefault("run_id", run_id)
            if "sequence" not in metadata:
                metadata["sequence"] = self._runtime.state.next_sequence()
        self._bus.emit(
            replace(
                event,
                metadata=metadata,
                session_id=event.session_id or self._session_id,
                run_id=event.run_id or run_id,
                tool_call_id=event.tool_call_id or metadata.get("tool_call_id"),
                operation_id=event.operation_id or metadata.get("operation_id"),
                phase=event.phase or metadata.get("phase"),
                elapsed_ms=event.elapsed_ms or metadata.get("elapsed_ms"),
                error_code=event.error_code or metadata.get("error_code"),
                retryable=(
                    event.retryable
                    if event.retryable is not None
                    else metadata.get("retryable")
                ),
                cleanup_uncertain=(
                    event.cleanup_uncertain
                    if event.cleanup_uncertain is not None
                    else metadata.get("cleanup_uncertain")
                ),
                cleanup_status=event.cleanup_status or metadata.get("cleanup_status"),
                side_effect_state=event.side_effect_state or metadata.get("side_effect_state"),
            )
        )


__all__ = ["SessionEventMixin"]
