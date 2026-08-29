"""Bounded, string-compatible output governance shared by concrete tools."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal

from .truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, truncate_head, truncate_tail

OutputDirection = Literal["head", "tail"]


@dataclass(frozen=True)
class OutputPolicy:
    """Hard output limits and the portion of text worth retaining."""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_lines: int = DEFAULT_MAX_LINES
    direction: OutputDirection = "head"
    marker: str = "\n[输出已截断]"

    def __post_init__(self) -> None:
        if type(self.max_bytes) is not int or self.max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        if type(self.max_lines) is not int or self.max_lines < 1:
            raise ValueError("max_lines must be a positive integer")
        if self.direction not in {"head", "tail"}:
            raise ValueError("direction must be 'head' or 'tail'")


@dataclass(frozen=True)
class GovernedOutput:
    """Tool-layer neutral output facts, independent from core contracts."""

    content: str
    output_metadata: dict[str, Any] = field(default_factory=dict)


class GovernedText(str):
    """A bounded string carrying metadata without breaking legacy callers."""

    output_metadata: dict[str, Any]
    content: str

    def __new__(cls, content: str, output_metadata: dict[str, Any]) -> "GovernedText":
        value = str.__new__(cls, content)
        value.content = content
        value.output_metadata = dict(output_metadata)
        return value


def govern_text(
    text: str,
    policy: OutputPolicy | None = None,
    **metadata: Any,
) -> GovernedText:
    """Apply deterministic head/tail limits and attach structured facts."""
    policy = policy or OutputPolicy()
    original = str(text)
    if policy.direction == "tail":
        bounded, truncation = truncate_tail(
            original, max_lines=policy.max_lines, max_bytes=policy.max_bytes
        )
    else:
        bounded, truncation = truncate_head(
            original, max_lines=policy.max_lines, max_bytes=policy.max_bytes
        )
    reason = None
    shown_bytes = len(bounded.encode("utf-8"))
    shown_lines = len(bounded.splitlines())
    if truncation.truncated:
        reason = "tool_bytes" if _byte_limited(original, bounded, policy) else "tool_lines"
        bounded = bounded + policy.marker
    facts = {
        "completeness": "truncated" if reason else "complete",
        "total_bytes": truncation.total_bytes,
        "total_lines": truncation.total_lines,
        "shown_bytes": shown_bytes,
        "shown_lines": shown_lines,
        "truncated_by": reason,
        "source": "tool",
        **metadata,
    }
    return GovernedText(bounded, facts)


def redact_metadata_text(text: str) -> str:
    """Remove common secret-like values before they enter diagnostics."""
    return re.sub(
        r"(?i)\b(api[_-]?key|token|password|secret|authorization)\b(\s*[:=]\s*)\S+",
        r"\1\2<redacted>",
        str(text),
    )


def _byte_limited(original: str, bounded: str, policy: OutputPolicy) -> bool:
    """Detect the byte limit without relying on truncate's final reason."""
    if len(original.encode("utf-8")) <= policy.max_bytes:
        return False
    # A line limit can also be hit first.  Byte cutting is observable when the
    # retained body itself reaches the configured byte boundary.
    return len(bounded.encode("utf-8")) >= policy.max_bytes


__all__ = [
    "GovernedOutput",
    "GovernedText",
    "OutputPolicy",
    "govern_text",
    "redact_metadata_text",
]
