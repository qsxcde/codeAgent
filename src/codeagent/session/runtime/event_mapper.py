"""Mapping between core and session events."""

from __future__ import annotations

from codeagent.core.events import AgentEvent, EventType


class EventMapper:
    """Translate core Agent lifecycle events to session events."""

    @staticmethod
    def map_agent_event(event: AgentEvent) -> list[AgentEvent]:
        if event.type == EventType.MESSAGE_UPDATE:
            if isinstance(event.payload, dict):
                kind = event.payload.get("type")
                if kind == "thinking_delta":
                    return [
                        AgentEvent(EventType.THINKING_DELTA, event.payload.get("text", {}))
                    ]
                if kind in {"tool_call", "tool_call_delta"}:
                    return [
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
                    ]
            return [AgentEvent(EventType.TEXT_DELTA, event.payload)]
        if event.type == EventType.MESSAGE_END:
            message = event.payload
            if getattr(message, "content", ""):
                return []
            return [AgentEvent(EventType.AGENT_MESSAGE, "")]
        if event.type == EventType.TOOL_EXECUTION_START:
            payload = event.payload or {}
            return [
                AgentEvent(
                    EventType.TOOL_STARTED,
                    payload=payload,
                    metadata={
                        "tool_call_id": payload.get("tool_call_id"),
                        "tool_name": payload.get("tool_name"),
                    },
                )
            ]
        if event.type == EventType.TOOL_EXECUTION_UPDATE:
            return [AgentEvent(EventType.TOOL_PROGRESS, event.payload, event.metadata)]
        if event.type == EventType.TOOL_EXECUTION_END:
            result = event.payload
            metadata = dict(event.metadata or {})
            metadata.update(
                {
                    "tool_call_id": getattr(result, "tool_call_id", None),
                    "status": getattr(result, "status", None),
                    "error": getattr(result, "error", False),
                    "cleanup_uncertain": getattr(result, "cleanup_confirmed", True)
                    is False,
                }
            )
            return [
                AgentEvent(
                    EventType.TOOL_FINISHED,
                    getattr(result, "content", result),
                    metadata=metadata,
                ),
                AgentEvent(
                    EventType.TOOL_RESULT,
                    getattr(result, "content", result),
                    metadata=metadata,
                ),
            ]
        return [event]


class SideEffectObserver:
    """Track whether a run may have produced external side effects."""

    def __init__(self) -> None:
        self.state = "none"
        self.cleanup_uncertain = False

    def reset(self) -> None:
        self.state = "none"
        self.cleanup_uncertain = False

    def observe(self, event: AgentEvent) -> None:
        if event.type == EventType.TOOL_STARTED:
            self.state = "possible"
        elif event.type == EventType.TOOL_FINISHED:
            metadata = dict(event.metadata or {})
            if metadata.get("cleanup_uncertain"):
                self.cleanup_uncertain = True
                self.state = "uncertain"
            elif metadata.get("status") not in {None, "ok", "rejected"}:
                self.state = "possible"
