"""Subagent 结构化结果的有限统计展示。"""

from __future__ import annotations

from typing import Any


def render_result_stats(payload: dict[str, Any]) -> str:
    """Summarize result collections without rendering their contents."""
    parts: list[str] = []
    for key, label in (("findings", "结论"), ("evidence", "证据")):
        value = payload.get(key)
        if isinstance(value, (list, tuple)):
            parts.append(f"{label}{min(len(value), 999)}")
    usage = payload.get("usage")
    if isinstance(usage, dict):
        input_tokens = _nonnegative_int(usage.get("input_tokens"))
        output_tokens = _nonnegative_int(usage.get("output_tokens"))
        if input_tokens is not None or output_tokens is not None:
            parts.append(f"token {input_tokens or 0}/{output_tokens or 0}")
    if payload.get("artifact") is not None:
        parts.append("产物 1")
    return " · ".join(parts)


def _nonnegative_int(value: Any) -> int | None:
    try:
        return max(0, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["render_result_stats"]
