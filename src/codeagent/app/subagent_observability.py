"""共享的 headless Subagent 状态行投影。"""

from __future__ import annotations

from typing import Any

_MAX_LINE_CHARS = 240
_MAX_ID_CHARS = 48
_MAX_FIELD_CHARS = 64
_MAX_SUMMARY_CHARS = 96
_TERMINAL = frozenset({"completed", "failed", "timed_out", "cancelled", "rejected"})
_SUBAGENT_EVENT_TYPES = frozenset(
    {"subagent_queued", "subagent_started", "subagent_progress", "subagent_finished"}
)


def _bounded(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _metadata(event: Any) -> dict[str, Any]:
    metadata = dict(event.metadata or {})
    for name in (
        "delegation_id",
        "subagent_status",
        "status",
        "child_phase",
        "phase",
        "tool_name",
        "elapsed_ms",
        "reason_code",
        "error_code",
        "cleanup_uncertain",
    ):
        value = getattr(event, name, None)
        if value is not None:
            metadata.setdefault(name, value)
    return metadata


def _payload(event: Any) -> dict[str, Any]:
    return event.payload if isinstance(event.payload, dict) else {}


def _status(event: Any, metadata: dict[str, Any], payload: dict[str, Any]) -> str:
    value = metadata.get("subagent_status") or metadata.get("status") or payload.get("subagent_status")
    if value:
        return _bounded(value, _MAX_FIELD_CHARS)
    return {
        "subagent_queued": "queued",
        "subagent_started": "running",
        "subagent_progress": "running",
        "subagent_finished": "failed",
    }.get(event.type, "unknown")


def _phase(metadata: dict[str, Any], payload: dict[str, Any]) -> str:
    return _bounded(metadata.get("child_phase") or metadata.get("phase") or payload.get("child_phase"), 48)


def _reason(metadata: dict[str, Any], payload: dict[str, Any]) -> str:
    failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
    return _bounded(
        metadata.get("reason_code")
        or metadata.get("error_code")
        or failure.get("reason_code"),
        _MAX_FIELD_CHARS,
    )


def _elapsed(metadata: dict[str, Any], payload: dict[str, Any]) -> int | None:
    value = metadata.get("elapsed_ms") or payload.get("elapsed_ms")
    try:
        return max(0, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


class SubagentLineProjector:
    """Emit one bounded, machine-readable line per visible child transition."""

    def __init__(self) -> None:
        self._last_state: dict[str, tuple[Any, ...]] = {}
        self._terminal_ids: set[str] = set()

    def project(self, event: Any) -> str | None:
        """Return a line for a new valid state, or ``None`` for duplicates."""
        if event.type not in _SUBAGENT_EVENT_TYPES:
            return None
        metadata = _metadata(event)
        payload = _payload(event)
        delegation_id = _bounded(metadata.get("delegation_id"), _MAX_ID_CHARS)
        if not delegation_id or delegation_id in self._terminal_ids:
            return None
        status = _status(event, metadata, payload)
        phase = _phase(metadata, payload)
        elapsed_ms = _elapsed(metadata, payload)
        reason = _reason(metadata, payload)
        cleanup_uncertain = bool(metadata.get("cleanup_uncertain") or payload.get("cleanup_uncertain"))
        summary = _bounded(payload.get("summary"), _MAX_SUMMARY_CHARS) if status in _TERMINAL else ""
        state = (status, phase, elapsed_ms, reason, cleanup_uncertain, summary)
        if self._last_state.get(delegation_id) == state:
            return None
        self._last_state[delegation_id] = state
        if status in _TERMINAL:
            self._terminal_ids.add(delegation_id)

        fields = [f"id={delegation_id}", f"status={status}"]
        if phase:
            fields.append(f"phase={phase}")
        if elapsed_ms is not None:
            fields.append(f"elapsed_ms={elapsed_ms}")
        tool_name = _bounded(metadata.get("tool_name") or payload.get("tool_name"), _MAX_FIELD_CHARS)
        if tool_name:
            fields.append(f"tool={tool_name}")
        if reason:
            fields.append(f"reason={reason}")
        if cleanup_uncertain:
            fields.append("cleanup_uncertain=true")
        if summary:
            fields.append(f"summary={summary}")
        line = "子Agent状态: " + " ".join(fields)
        return line if len(line) <= _MAX_LINE_CHARS else line[: _MAX_LINE_CHARS - 1] + "…"


__all__ = ["SubagentLineProjector"]
