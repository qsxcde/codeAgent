"""Small immutable value objects used by context diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

WindowCertainty = Literal["known", "fallback", "uncertain", "unknown"]


@dataclass(frozen=True)
class CompactionDiagnostic:
    """The latest compaction outcome without copying message bodies."""

    trigger: str = "unknown"
    status: str = "unknown"
    reason_code: str | None = None
    reason: str | None = None
    before_input_tokens: int | None = None
    after_input_tokens: int | None = None
    target_tokens: int | None = None
    summarized_entry_ids: tuple[str, ...] = ()
    kept_entry_ids: tuple[str, ...] = ()

    @property
    def cropped_range(self) -> tuple[str, str] | None:
        return _range_of(self.summarized_entry_ids)

    @property
    def retained_range(self) -> tuple[str, str] | None:
        return _range_of(self.kept_entry_ids)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "status": self.status,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "before_input_tokens": self.before_input_tokens,
            "after_input_tokens": self.after_input_tokens,
            "target_tokens": self.target_tokens,
            "cropped_range": self.cropped_range,
            "retained_range": self.retained_range,
        }


@dataclass(frozen=True)
class ToolResultDiagnostic:
    """Bounded metadata describing one governed tool result."""

    tool_call_id: str | None = None
    status: str = "unknown"
    original_bytes: int | None = None
    shown_bytes: int | None = None
    action: str = "none"
    reason: str | None = None
    facts_complete: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "status": self.status,
            "original_bytes": self.original_bytes,
            "shown_bytes": self.shown_bytes,
            "action": self.action,
            "reason": self.reason,
            "facts_complete": self.facts_complete,
        }


def _range_of(entry_ids: tuple[str, ...]) -> tuple[str, str] | None:
    if not entry_ids:
        return None
    return entry_ids[0], entry_ids[-1]


__all__ = [
    "CompactionDiagnostic",
    "ToolResultDiagnostic",
    "WindowCertainty",
]
