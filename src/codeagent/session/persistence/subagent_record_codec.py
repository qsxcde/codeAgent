"""Event and JSONL codecs for bounded Subagent records."""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.events import SUBAGENT_EVENT_TYPES, AgentEvent

from .subagent_record_model import SubagentRunRecord
from .subagent_record_values import bounded_result


def record_from_event(
    event: AgentEvent,
    expected_parent_run_id: str | None = None,
) -> SubagentRunRecord | None:
    """Project one parent-facing event into a bounded persistence record."""
    if event.type not in SUBAGENT_EVENT_TYPES:
        return None
    metadata = dict(event.metadata or {})
    delegation_id = _value(event, metadata, "delegation_id")
    parent_run_id = _value(event, metadata, "parent_run_id")
    if not delegation_id or not parent_run_id:
        return None
    if expected_parent_run_id is not None and str(parent_run_id) != str(expected_parent_run_id):
        return None
    status = _value(event, metadata, "subagent_status") or _value(event, metadata, "status")
    status = str(
        getattr(status, "value", status or ("queued" if event.type == "subagent_queued" else "running"))
    )
    payload = event.payload if isinstance(event.payload, dict) else {}
    failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
    reason_code = (
        _value(event, metadata, "reason_code")
        or _value(event, metadata, "error_code")
        or str(failure.get("reason_code") or "")
    )
    diagnostics = payload.get("diagnostics", ())
    if not diagnostics and payload.get("diagnostic"):
        diagnostics = (payload["diagnostic"],)
    if not isinstance(diagnostics, (list, tuple)):
        diagnostics = (diagnostics,)
    result = payload if event.type == "subagent_finished" else _progress_result(payload)
    return SubagentRunRecord(
        delegation_id=str(delegation_id),
        parent_run_id=str(parent_run_id),
        child_run_id=_optional_value(event, metadata, "child_run_id"),
        attempt_id=_optional_value(event, metadata, "attempt_id"),
        profile=str(_value(event, metadata, "profile") or ""),
        task_label=str(_value(event, metadata, "task_label") or ""),
        status=status,
        phase=str(
            _value(event, metadata, "child_phase")
            or _value(event, metadata, "phase")
            or status
        ),
        summary=str(payload.get("summary") or ""),
        reason_code=reason_code,
        diagnostics=tuple(str(item) for item in diagnostics if item is not None),
        cleanup_uncertain=bool(
            _value(event, metadata, "cleanup_uncertain") or payload.get("cleanup_uncertain")
        ),
        result=result,
    )


def record_from_entry(entry: dict[str, Any]) -> SubagentRunRecord:
    """Decode a JSONL subagent entry, raising for malformed required fields."""
    if entry.get("type") != "subagent":
        raise ValueError("not a subagent entry")
    delegation_id = entry.get("delegationId", entry.get("delegation_id"))
    parent_run_id = entry.get("parentRunId", entry.get("parent_run_id"))
    status = entry.get("status")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (delegation_id, parent_run_id, status)
    ):
        raise ValueError("subagent entry is missing required fields")
    diagnostics = entry.get("diagnostics", ())
    if not isinstance(diagnostics, (list, tuple)):
        raise ValueError("subagent diagnostics must be a list")
    return SubagentRunRecord(
        id=str(entry.get("id") or ""),
        timestamp=str(entry.get("timestamp") or ""),
        delegation_id=delegation_id,
        parent_run_id=parent_run_id,
        child_run_id=_entry_value(entry, "childRunId", "child_run_id"),
        attempt_id=_entry_value(entry, "attemptId", "attempt_id"),
        profile=str(entry.get("profile") or ""),
        task_label=str(entry.get("taskLabel", entry.get("task_label")) or ""),
        status=status,
        phase=str(entry.get("phase") or ""),
        summary=str(entry.get("summary") or ""),
        reason_code=str(entry.get("reasonCode", entry.get("reason_code")) or ""),
        diagnostics=tuple(str(item) for item in diagnostics),
        cleanup_uncertain=entry.get("cleanupUncertain", entry.get("cleanup_uncertain", False)),
        result=bounded_result(entry.get("result")),
    )


def record_to_entry(
    record: SubagentRunRecord,
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Encode a record without leaking internal Python objects."""
    return {
        "type": "subagent",
        "id": record.id,
        "timestamp": timestamp or record.timestamp,
        "delegationId": record.delegation_id,
        "parentRunId": record.parent_run_id,
        "childRunId": record.child_run_id,
        "attemptId": record.attempt_id,
        "profile": record.profile,
        "taskLabel": record.task_label,
        "status": record.status,
        "phase": record.phase,
        "summary": record.summary,
        "reasonCode": record.reason_code,
        "diagnostics": list(record.diagnostics),
        "cleanupUncertain": record.cleanup_uncertain,
        "result": record.result,
    }


def _value(event: AgentEvent, metadata: dict[str, Any], name: str) -> Any:
    value = getattr(event, name, None)
    return value if value is not None else metadata.get(name)


def _optional_value(event: AgentEvent, metadata: dict[str, Any], name: str) -> str | None:
    value = _value(event, metadata, name)
    return str(value) if value else None


def _entry_value(entry: dict[str, Any], *names: str) -> str | None:
    for name in names:
        if entry.get(name):
            return str(entry[name])
    return None


def _progress_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(payload[key])[:512]
        for key in ("tool_name", "child_event_type", "child_phase", "reason", "diagnostic", "elapsed_ms")
        if payload.get(key) is not None
    }


__all__ = ["record_from_entry", "record_from_event", "record_to_entry"]
