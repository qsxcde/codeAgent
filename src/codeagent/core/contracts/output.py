"""Structured facts describing bounded tool output."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

__all__ = ["OutputCompleteness", "ToolOutputMetadata"]


class OutputCompleteness:
    """Stable completeness values for governed tool output."""

    COMPLETE = "complete"
    TRUNCATED = "truncated"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    ALL = (COMPLETE, TRUNCATED, INCOMPLETE, UNKNOWN, UNSUPPORTED)


@dataclass(frozen=True)
class ToolOutputMetadata:
    """Facts shared by model requests, events, session storage and TUI.

    ``content`` remains on :class:`ToolResult`; this value object only keeps
    bounded-output facts. ``source=legacy`` explicitly identifies results
    produced by adapters that cannot prove completeness.
    """

    completeness: str = OutputCompleteness.UNKNOWN
    total_bytes: int | None = None
    total_lines: int | None = None
    shown_bytes: int | None = None
    shown_lines: int | None = None
    truncated_by: str | None = None
    path: str | None = None
    range_start: int | None = None
    range_end: int | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    stderr_summary: str | None = None
    change_summary: str | None = None
    artifact_path: str | None = None
    artifact_ref: str | None = None
    continuation: str | None = None
    semantic_success: bool | None = None
    source: str = "structured"
    unsupported_blocks: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.completeness not in OutputCompleteness.ALL:
            raise ValueError(f"unsupported output completeness: {self.completeness}")
        for name in (
            "total_bytes",
            "total_lines",
            "shown_bytes",
            "shown_lines",
            "range_start",
            "range_end",
            "duration_ms",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if not self.source:
            raise ValueError("source must be a non-empty string")
        if not isinstance(self.unsupported_blocks, (list, tuple)):
            raise ValueError("unsupported_blocks must be a sequence")
        blocks = []
        for block in self.unsupported_blocks:
            if not isinstance(block, dict):
                raise ValueError("unsupported_blocks entries must be objects")
            blocks.append(copy.deepcopy(block))
        object.__setattr__(self, "unsupported_blocks", tuple(blocks))

    @property
    def is_truncated(self) -> bool:
        """Whether content is known to omit some source output."""
        return self.completeness in {
            OutputCompleteness.TRUNCATED,
            OutputCompleteness.INCOMPLETE,
        }

    @property
    def is_recoverable(self) -> bool:
        """Whether an artifact or continuation can supply omitted output."""
        return bool(self.artifact_path or self.artifact_ref or self.continuation)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe detached representation."""
        return {
            "completeness": self.completeness,
            "total_bytes": self.total_bytes,
            "total_lines": self.total_lines,
            "shown_bytes": self.shown_bytes,
            "shown_lines": self.shown_lines,
            "truncated_by": self.truncated_by,
            "path": self.path,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stderr_summary": self.stderr_summary,
            "change_summary": self.change_summary,
            "artifact_path": self.artifact_path,
            "artifact_ref": self.artifact_ref,
            "continuation": self.continuation,
            "semantic_success": self.semantic_success,
            "source": self.source,
            "unsupported_blocks": [copy.deepcopy(block) for block in self.unsupported_blocks],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ToolOutputMetadata":
        """Decode optional session metadata, ignoring unknown future fields."""
        if not isinstance(value, dict):
            return cls(source="legacy")
        allowed = {
            "completeness",
            "total_bytes",
            "total_lines",
            "shown_bytes",
            "shown_lines",
            "truncated_by",
            "path",
            "range_start",
            "range_end",
            "exit_code",
            "duration_ms",
            "stderr_summary",
            "change_summary",
            "artifact_path",
            "artifact_ref",
            "continuation",
            "semantic_success",
            "source",
            "unsupported_blocks",
        }
        data = {key: value[key] for key in allowed if key in value}
        completeness = data.get("completeness", OutputCompleteness.UNKNOWN)
        if completeness not in OutputCompleteness.ALL:
            completeness = OutputCompleteness.UNKNOWN
        data["completeness"] = completeness
        data["source"] = str(data.get("source") or "legacy")
        return cls(**data)
