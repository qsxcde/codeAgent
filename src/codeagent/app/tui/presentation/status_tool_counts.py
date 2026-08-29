"""状态栏工具生命周期聚合的紧凑文案。"""

from __future__ import annotations

from collections.abc import Mapping

_LABELS = {
    "queued": "排",
    "running": "运",
    "awaiting_confirmation": "待",
    "completed": "完",
    "failed": "败",
    "rejected": "拒",
    "timed_out": "超",
    "cancelled": "取",
    "cleanup_uncertain": "清",
}


def render_tool_counts(counts: Mapping[str, int]) -> str:
    """Render non-zero tool states without widening the status-bar zones."""
    return " ".join(
        f"{_LABELS.get(status, status[:1])}{count}"
        for status, count in counts.items()
        if count > 0
    )
