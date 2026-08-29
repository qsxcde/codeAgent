"""状态栏上下文信息区的固定宽度渲染。"""

from __future__ import annotations

from .primitives import RichLine, _format_token_count, _seg
from .theme import ACCENT, DIM


def render_context_spans(
    width: int,
    tokens: int | None,
    window: int | None,
    *,
    meter_width: int = 8,
) -> RichLine:
    """Render context usage using the available right-zone budget."""
    if window is None or window <= 0:
        return [_seg("上下文 —", fg=DIM)]
    used = tokens
    if used is None:
        filled = 0
        used_label = "—"
        percent_label = ""
    else:
        ratio = max(0.0, min(1.0, used / window))
        filled = round(ratio * meter_width)
        percent = ratio * 100
        used_label = _format_token_count(max(0, used))
        percent_label = f"{percent:.1f}%"

    if width >= 28:
        meter = "▰" * filled + "▱" * (meter_width - filled)
        label = f"上下文 {used_label} / {_format_token_count(window)}"
        if percent_label:
            label += f" · {percent_label}"
        return [_seg(f"{meter} ", fg=ACCENT), _seg(label, fg=ACCENT)]
    if width >= 18:
        if used is None:
            return [_seg(f"上下文 — / {_format_token_count(window)}", fg=ACCENT)]
        compact_width = 4
        compact_filled = round((filled / meter_width) * compact_width)
        meter = "▰" * compact_filled + "▱" * (compact_width - compact_filled)
        label = f"{used_label}/{_format_token_count(window)}"
        if percent_label and width >= 22:
            label += f" {percent_label}"
        return [_seg(f"{meter} ", fg=ACCENT), _seg(label, fg=ACCENT)]
    if width >= 12:
        return [_seg(f"{used_label}/{_format_token_count(window)}", fg=ACCENT)]
    if width >= 8:
        return [_seg(percent_label or f"/{_format_token_count(window)}", fg=ACCENT)]
    return [_seg(percent_label[:width] or "—", fg=ACCENT)]
