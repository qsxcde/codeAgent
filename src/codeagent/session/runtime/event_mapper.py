"""Mapping between core and session events."""

from __future__ import annotations

from dataclasses import replace

from codeagent.core.contracts.events import AgentEvent, EventType


class EventMapper:
    """Translate core Agent lifecycle events to session events."""

    @staticmethod
    def map_agent_event(event: AgentEvent) -> list[AgentEvent]:
        def inherit(mapped: AgentEvent) -> AgentEvent:
            """Keep correlation fields while translating event types."""
            metadata = dict(mapped.metadata or {})
            source_metadata = dict(event.metadata or {})
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
                "cleanup_status",
                "side_effect_state",
            ):
                value = getattr(event, field_name, None)
                if value is not None:
                    metadata.setdefault(field_name, value)
                if field_name in source_metadata:
                    metadata.setdefault(field_name, source_metadata[field_name])
            return replace(
                mapped,
                metadata=metadata,
                session_id=mapped.session_id or event.session_id,
                run_id=mapped.run_id or event.run_id,
                tool_call_id=mapped.tool_call_id or event.tool_call_id,
                operation_id=mapped.operation_id or event.operation_id,
                phase=mapped.phase or event.phase,
                elapsed_ms=mapped.elapsed_ms or event.elapsed_ms,
                error_code=mapped.error_code or event.error_code,
                retryable=(
                    mapped.retryable
                    if mapped.retryable is not None
                    else event.retryable
                ),
                cleanup_uncertain=(
                    mapped.cleanup_uncertain
                    if mapped.cleanup_uncertain is not None
                    else event.cleanup_uncertain
                ),
                cleanup_status=(
                    mapped.cleanup_status
                    if mapped.cleanup_status is not None
                    else event.cleanup_status
                ),
                side_effect_state=mapped.side_effect_state or event.side_effect_state,
            )

        if event.type == EventType.MESSAGE_UPDATE:
            if isinstance(event.payload, dict):
                kind = event.payload.get("type")
                if kind == "thinking_delta":
                    return [inherit(
                        AgentEvent(EventType.THINKING_DELTA, event.payload.get("text", {}))
                    )]
                if kind in {"tool_call", "tool_call_delta"}:
                    return [inherit(
                        AgentEvent(
                            EventType.TOOL_CALL,
                            payload=[
                                {
                                    "id": event.payload.get("tool_call_id"),
                                    "name": event.payload.get("tool_name", ""),
                                    "args": event.payload.get("arguments", {}),
                                }
                            ],
                        )
                    )]
            return [inherit(AgentEvent(EventType.TEXT_DELTA, event.payload))]
        if event.type == EventType.MESSAGE_END:
            message = event.payload
            if getattr(message, "content", ""):
                return []
            return [inherit(AgentEvent(EventType.AGENT_MESSAGE, ""))]
        if event.type == EventType.TOOL_EXECUTION_START:
            payload = event.payload or {}
            return [inherit(
                AgentEvent(
                    EventType.TOOL_STARTED,
                    payload=payload,
                    metadata={
                        "tool_call_id": payload.get("tool_call_id"),
                        "tool_name": payload.get("tool_name"),
                    },
                )
            )]
        if event.type == EventType.TOOL_EXECUTION_UPDATE:
            return [inherit(AgentEvent(EventType.TOOL_PROGRESS, event.payload, event.metadata))]
        if event.type == EventType.TOOL_EXECUTION_END:
            result = event.payload
            metadata = dict(event.metadata or {})
            status = getattr(result, "status", None)
            error_code = {
                "invalid_arguments": "tool_invalid_arguments",
                "failed": "tool_error",
                "rejected": "confirmation_rejected",
                "timed_out": "tool_timeout",
                "cancelled": "tool_cancelled",
                "cleanup_uncertain": "tool_cleanup_uncertain",
            }.get(status)
            metadata.update(
                {
                    "tool_call_id": getattr(result, "tool_call_id", None),
                    "status": status,
                    "error": getattr(result, "error", False),
                    "cleanup_status": getattr(result, "cleanup_status", None),
                    "cleanup_uncertain": bool(
                        getattr(result, "cleanup_uncertain", False)
                    ),
                    "cleanup_error": getattr(result, "cleanup_error", None),
                }
            )
            if error_code is not None:
                metadata["error_code"] = error_code
            return [
                inherit(
                    AgentEvent(
                        EventType.TOOL_FINISHED,
                        getattr(result, "content", result),
                        metadata=metadata,
                        error_code=error_code,
                        cleanup_status=getattr(result, "cleanup_status", None),
                    )
                ),
                inherit(
                    AgentEvent(
                        EventType.TOOL_RESULT,
                        getattr(result, "content", result),
                        metadata=metadata,
                        error_code=error_code,
                        cleanup_status=getattr(result, "cleanup_status", None),
                    )
                ),
            ]
        return [inherit(event)]


class SideEffectObserver:
    """Track whether a run may have produced external side effects."""

    def __init__(self) -> None:
        self.state = "none"
        self.cleanup_uncertain = False
        self.cleanup_status = "not_required"

    def reset(self) -> None:
        self.state = "none"
        self.cleanup_uncertain = False
        self.cleanup_status = "not_required"

    def observe(self, event: AgentEvent) -> None:
        if event.type == EventType.TOOL_STARTED:
            self.state = "possible"
        elif event.type == EventType.TOOL_FINISHED:
            metadata = dict(event.metadata or {})
            if metadata.get("cleanup_status"):
                self.cleanup_status = str(metadata["cleanup_status"])
            if metadata.get("cleanup_uncertain"):
                self.cleanup_uncertain = True
                self.state = "uncertain"
            elif metadata.get("status") not in {None, "ok", "rejected"}:
                self.state = "possible"
        elif event.type == EventType.ABORTED:
            metadata = dict(event.metadata or {})
            if metadata.get("cleanup_status"):
                self.cleanup_status = str(metadata["cleanup_status"])
            if metadata.get("cleanup_uncertain"):
                self.cleanup_uncertain = True
                self.state = "uncertain"
