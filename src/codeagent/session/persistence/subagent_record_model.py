"""Domain model and folding rules for parent-owned Subagent records."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from codeagent.core.contracts.messages import new_id

from .subagent_record_values import bounded_result

MAX_RECORD_ID_CHARS = 128
MAX_TASK_LABEL_CHARS = 96
MAX_PROFILE_CHARS = 40
MAX_SUMMARY_CHARS = 16_000
MAX_DIAGNOSTICS = 8
MAX_DIAGNOSTIC_CHARS = 2_000

TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "timed_out", "cancelled", "rejected", "abandoned"}
)
NONTERMINAL_STATUSES = frozenset(
    {"created", "queued", "starting", "running", "waiting_confirmation", "cancelling"}
)
_KNOWN_STATUSES = TERMINAL_STATUSES | NONTERMINAL_STATUSES


@dataclass(frozen=True)
class SubagentRunRecord:
    """A bounded, parent-owned fact about one delegated run."""

    delegation_id: str
    parent_run_id: str
    status: str
    phase: str = ""
    task_label: str = ""
    profile: str = ""
    child_run_id: str | None = None
    attempt_id: str | None = None
    summary: str = ""
    reason_code: str = ""
    diagnostics: tuple[str, ...] = ()
    cleanup_uncertain: bool = False
    result: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        for name in ("delegation_id", "parent_run_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name, MAX_RECORD_ID_CHARS))
        status = _text(self.status, 48)
        if status not in _KNOWN_STATUSES:
            raise ValueError(f"unknown Subagent record status: {status}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "phase", _text(self.phase, 64))
        object.__setattr__(self, "task_label", _single_line(self.task_label, MAX_TASK_LABEL_CHARS))
        object.__setattr__(self, "profile", _single_line(self.profile, MAX_PROFILE_CHARS))
        for name in ("child_run_id", "attempt_id"):
            value = getattr(self, name)
            object.__setattr__(self, name, _single_line(value, MAX_RECORD_ID_CHARS) if value else None)
        object.__setattr__(self, "summary", _text(self.summary, MAX_SUMMARY_CHARS))
        object.__setattr__(self, "reason_code", _single_line(self.reason_code, 96))
        object.__setattr__(self, "diagnostics", _diagnostics(self.diagnostics))
        if type(self.cleanup_uncertain) is not bool:
            raise TypeError("cleanup_uncertain must be a bool")
        object.__setattr__(self, "result", bounded_result(self.result))
        object.__setattr__(self, "id", _single_line(self.id, MAX_RECORD_ID_CHARS) or new_id())
        object.__setattr__(self, "timestamp", _single_line(self.timestamp, 64) or _now())

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status in NONTERMINAL_STATUSES

    def as_abandoned(self) -> SubagentRunRecord:
        """Return the read-only recovery view for an interrupted run."""
        diagnostics = list(self.diagnostics)
        if "process_restarted" not in diagnostics:
            diagnostics.append("process_restarted")
        return replace(
            self,
            status="abandoned",
            phase="recovered",
            reason_code="process_restarted",
            diagnostics=tuple(diagnostics),
            cleanup_uncertain=True,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a detached snake-case representation."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "delegation_id": self.delegation_id,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "attempt_id": self.attempt_id,
            "profile": self.profile,
            "task_label": self.task_label,
            "status": self.status,
            "phase": self.phase,
            "summary": self.summary,
            "reason_code": self.reason_code,
            "diagnostics": list(self.diagnostics),
            "cleanup_uncertain": self.cleanup_uncertain,
            "result": dict(self.result),
        }


def fold_records(records: Iterable[SubagentRunRecord]) -> list[SubagentRunRecord]:
    """Keep latest progress, while making the first terminal final."""
    folded: dict[str, SubagentRunRecord] = {}
    for record in records:
        current = folded.get(record.delegation_id)
        if current is not None and current.is_terminal:
            continue
        folded[record.delegation_id] = record
    return [record.as_abandoned() if record.is_active else record for record in folded.values()]


def _required(value: Any, name: str, limit: int) -> str:
    text = _single_line(value, limit)
    if not text:
        raise ValueError(f"{name} must be a non-empty string")
    return text


def _single_line(value: Any, limit: int) -> str:
    return _text(" ".join(str(value or "").split()), limit)


def _text(value: Any, limit: int) -> str:
    text = str(getattr(value, "value", value) or "")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _diagnostics(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("diagnostics must be a list or tuple")
    return tuple(_text(item, MAX_DIAGNOSTIC_CHARS) for item in value[:MAX_DIAGNOSTICS])


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"


__all__ = [
    "MAX_DIAGNOSTICS",
    "MAX_DIAGNOSTIC_CHARS",
    "MAX_PROFILE_CHARS",
    "MAX_RECORD_ID_CHARS",
    "MAX_SUMMARY_CHARS",
    "MAX_TASK_LABEL_CHARS",
    "NONTERMINAL_STATUSES",
    "SubagentRunRecord",
    "TERMINAL_STATUSES",
    "fold_records",
]
