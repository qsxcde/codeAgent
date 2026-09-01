"""状态栏 Subagent 委派聚合的紧凑文案。"""

from __future__ import annotations

from collections.abc import Mapping


_LABELS = (
    ("running", "运"),
    ("waiting", "等"),
    ("failed", "失败"),
)


def render_subagent_counts(counts: Mapping[str, int]) -> str:
    """Render non-zero child states inside the existing runtime zone."""
    parts = [
        f"{label}{max(0, int(counts.get(status, 0)))}"
        for status, label in _LABELS
        if int(counts.get(status, 0)) > 0
    ]
    return f"子Agent {' · '.join(parts)}" if parts else ""


__all__ = ["render_subagent_counts"]
