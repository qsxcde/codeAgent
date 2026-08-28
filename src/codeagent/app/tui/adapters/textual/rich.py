"""Textual 引擎使用的 Rich 样式和富文本转换。"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.color import Color
from textual.filter import LineFilter

from ...presentation.primitives import RichLine
from ...presentation.theme import BOLD, PALETTE


def _strip_default_bg(style: Style) -> Style:
    """重建 Style，仅移除终端默认背景。"""
    return Style(
        color=style.color,
        bold=style.bold,
        dim=style.dim,
        italic=style.italic,
        underline=style.underline,
        blink=style.blink,
        blink2=style.blink2,
        reverse=style.reverse,
        conceal=style.conceal,
        strike=style.strike,
        underline2=style.underline2,
        frame=style.frame,
        encircle=style.encircle,
        overline=style.overline,
        link=style.link,
        meta=style.meta,
    )


class _NoDefaultBackground(LineFilter):
    """剥离 Rich default 背景，保留显式色值背景。"""

    def apply(self, segments: list[Segment], background: Color) -> list[Segment]:
        return [
            (
                Segment(segment.text, _strip_default_bg(segment.style), segment.control)
                if segment.style is not None
                and segment.style.bgcolor is not None
                and segment.style.bgcolor.is_default
                else segment
            )
            for segment in segments
        ]


def _line_to_text(line: RichLine) -> Text:
    text = Text()
    for span in line:
        text.append(
            span.text,
            style=Style(
                color=PALETTE.get(span.fg) if span.fg else None,
                bgcolor=PALETTE.get(span.bg) if span.bg else None,
                bold=span.fg == BOLD,
            ),
        )
    return text


def rich_to_text(lines: list[RichLine]) -> Text:
    """把多行 RichLine 渲染为单块 Rich Text。"""
    text = Text()
    for index, line in enumerate(lines):
        text.append(_line_to_text(line))
        if index < len(lines) - 1:
            text.append("\n")
    return text
