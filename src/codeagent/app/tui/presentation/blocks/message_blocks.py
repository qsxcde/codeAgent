"""用户、助手和活动消息块。"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..primitives import (
    Component,
    RichLine,
    _cell_width,
    _seg,
    _wrap,
)
from ..theme import ACTIVITY, ASSISTANT_PROMPT, TEXT, USER_BG, USER_PROMPT


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


@dataclass
class _StreamLayout:
    """Incremental Markdown output for one terminal width."""

    stable_units: int = 0
    lines: list[RichLine] = field(default_factory=list)


class UserBlock(Component):
    """用户消息块：低对比提示符与连续的满宽深灰背景。"""

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt

    def render(self, width: int) -> list[RichLine]:
        width = max(1, width)
        body_width = max(1, width - 2)
        lines: list[RichLine] = []
        for index, text in enumerate(_wrap(self.prompt, body_width)):
            prefix = "› " if index == 0 else "  "
            rendered: RichLine = [
                _seg(prefix, fg=USER_PROMPT, bg=USER_BG),
                _seg(text, fg=TEXT, bg=USER_BG),
            ]
            padding = max(0, width - _cell_width(prefix) - _cell_width(text))
            if padding:
                rendered.append(_seg(" " * padding, bg=USER_BG))
            lines.append(rendered)
        return lines


class AssistantBlock(Component):
    """助手回复块：保留推理累积，只渲染用户可见正文。"""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        md_renderer: Callable[[str, int], list[RichLine]] | None = None,
    ) -> None:
        self._clock = clock
        self._md_renderer = md_renderer
        self._thinking_parts: list[str] = []
        self._body_parts: list[str] = []
        self._body_length = 0
        self._full_markdown_cache: dict[tuple[int, str], list[RichLine]] = {}
        self._stream_units: list[str] = []
        self._stream_pending_parts: list[str] = []
        self._stream_line_parts: list[str] = []
        self._stream_in_fence = False
        self._stream_layouts: dict[int, _StreamLayout] = {}
        self._finalized = False
        self.thinking_started: float | None = None
        self.thinking_ended: float | None = None

    def append_thinking(self, text: str) -> None:
        if self.thinking_started is None:
            self.thinking_started = self._clock()
        self._thinking_parts.append(text)
        self.touch()

    def append_text(self, text: str) -> None:
        if self.thinking_started is not None and self.thinking_ended is None:
            self.thinking_ended = self._clock()
        self._body_parts.append(text)
        self._body_length += len(text)
        self._append_stream_text(text)
        self._finalized = False
        self.touch()

    def finalize(self) -> None:
        """标记块结束，并强制下一次渲染使用完整 Markdown。"""
        self._finalized = True
        self._full_markdown_cache.clear()
        self.touch()

    @property
    def thinking(self) -> str:
        return "".join(self._thinking_parts)

    @property
    def body(self) -> str:
        return "".join(self._body_parts)

    @property
    def has_body(self) -> bool:
        """Return whether the block has content without joining all parts."""
        return self._body_length > 0

    @property
    def body_length(self) -> int:
        """Return the accumulated body size without materializing its text."""
        return self._body_length

    @staticmethod
    def _without_line_ending(line: str) -> str:
        return line.removesuffix("\n").removesuffix("\r")

    def _append_stream_text(self, text: str) -> None:
        """Split newly received text into stable lines and an unstable tail."""
        for part in text.splitlines(keepends=True):
            self._stream_line_parts.append(part)
            if not part.endswith(("\n", "\r")):
                continue
            line = "".join(self._stream_line_parts)
            self._stream_line_parts = []
            self._append_stream_line(line)

    def _append_stream_line(self, line: str) -> None:
        """Record one complete line while keeping open fences together."""
        raw = self._without_line_ending(line)
        if self._stream_in_fence:
            self._stream_pending_parts.append(line)
            if _FENCE_RE.match(raw):
                self._stream_in_fence = False
                self._release_stream_pending()
            return
        if _FENCE_RE.match(raw):
            self._stream_in_fence = True
            self._stream_pending_parts.append(line)
            return
        self._stream_units.append(raw)

    def _release_stream_pending(self) -> None:
        text = "".join(self._stream_pending_parts)
        self._stream_pending_parts = []
        self._stream_units.append(self._without_line_ending(text))

    def _stream_render(
        self, width: int, renderer: Callable[[str, int], list[RichLine]]
    ) -> list[RichLine]:
        """Render only new stable units plus the currently unfinished tail."""
        inner = max(1, width - 2)
        layout = self._stream_layout(inner)
        while layout.stable_units < len(self._stream_units):
            unit = self._stream_units[layout.stable_units]
            layout.lines.extend(renderer(unit, inner) if unit else [[]])
            layout.stable_units += 1
        tail = "".join((*self._stream_pending_parts, *self._stream_line_parts))
        parsed = [*layout.lines, *renderer(tail, inner)] if tail else layout.lines
        return parsed

    def _stream_layout(self, inner: int) -> _StreamLayout:
        layout = self._stream_layouts.get(inner)
        if layout is None:
            layout = _StreamLayout()
            self._stream_layouts[inner] = layout
            while len(self._stream_layouts) > 3:
                self._stream_layouts.pop(next(iter(self._stream_layouts)))
        if layout.stable_units > len(self._stream_units):
            layout = _StreamLayout()
            self._stream_layouts[inner] = layout
        return layout

    def _with_prompt(self, parsed: list[RichLine]) -> list[RichLine]:
        lines: list[RichLine] = []
        for index, line in enumerate(parsed):
            prefix = "• " if index == 0 else "  "
            lines.append([_seg(prefix, fg=ASSISTANT_PROMPT), *line])
        return lines

    async def render_progressive(self, width: int, *, yield_every: int = 32) -> list[RichLine]:
        """Prepare active Markdown in bounded units owned by the UI loop."""
        if self._finalized:
            return self.render(width)
        if not self.has_body:
            return []
        renderer = self._md_renderer
        if renderer is None:
            from codeagent.app.tui.presentation.md_renderer import md_renderer as renderer
        inner = max(1, width - 2)
        layout = self._stream_layout(inner)
        for index in range(layout.stable_units, len(self._stream_units)):
            unit = self._stream_units[index]
            layout.lines.extend(renderer(unit, inner) if unit else [[]])
            layout.stable_units += 1
            if (index + 1) % max(1, yield_every) == 0:
                await asyncio.sleep(0)
        tail = "".join((*self._stream_pending_parts, *self._stream_line_parts))
        parsed = [*layout.lines, *renderer(tail, inner)] if tail else layout.lines
        return self._with_prompt(parsed)

    def render(self, width: int) -> list[RichLine]:
        if not self.has_body:
            return []
        renderer = self._md_renderer
        if renderer is None:
            from codeagent.app.tui.presentation.md_renderer import md_renderer as renderer
        inner = max(1, width - 2)
        if self._finalized:
            body = self.body
            full_key = (inner, body)
            if full_key in self._full_markdown_cache:
                return self._full_markdown_cache[full_key]
            parsed = renderer(body, inner)
        else:
            parsed = self._stream_render(width, renderer)
        lines: list[RichLine] = []
        for index, line in enumerate(parsed):
            prefix = "• " if index == 0 else "  "
            lines.append([_seg(prefix, fg=ASSISTANT_PROMPT), *line])
        if self._finalized:
            self._full_markdown_cache[full_key] = lines
        return lines


class ActivityBlock(Component):
    """不写入历史的轻量等待提示。"""

    _FRAMES = (" ·", " ··", " ···")

    def __init__(self, frame: int = 0) -> None:
        self.frame = frame

    def render(self, width: int) -> list[RichLine]:
        suffix = self._FRAMES[self.frame % len(self._FRAMES)]
        return [[_seg("• ", fg=ASSISTANT_PROMPT), _seg(f"思考中{suffix}", fg=ACTIVITY)]]
