"""用户、助手和活动消息块。"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..primitives import (
    Component,
    RichLine,
    _cell_width,
    _seg,
    _wrap,
)
from ..theme import ACTIVITY, ASSISTANT_PROMPT, TEXT, USER_BG, USER_PROMPT


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
        self._stable_markdown_cache: dict[tuple[int, str], list[RichLine]] = {}
        self._full_markdown_cache: dict[tuple[int, str], list[RichLine]] = {}
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
        self._finalized = False
        self.touch()

    def finalize(self) -> None:
        """标记块结束，并强制下一次渲染使用完整 Markdown。"""
        self._finalized = True
        self._full_markdown_cache.clear()
        self.touch()

    @staticmethod
    def _stable_prefix(body: str) -> str:
        end = body.rfind("\n")
        if end < 0:
            return ""
        prefix = body[: end + 1]
        in_fence = False
        for line in prefix.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
        return "" if in_fence else prefix

    @property
    def thinking(self) -> str:
        return "".join(self._thinking_parts)

    @property
    def body(self) -> str:
        return "".join(self._body_parts)

    def render(self, width: int) -> list[RichLine]:
        if not self.body:
            return []
        inner = max(1, width - 2)
        renderer = self._md_renderer
        if renderer is None:
            from codeagent.app.tui.presentation.md_renderer import md_renderer as renderer
        body = self.body
        full_key = (inner, body)
        if self._finalized and full_key in self._full_markdown_cache:
            return self._full_markdown_cache[full_key]
        stable = "" if self._finalized else self._stable_prefix(body)
        if stable:
            stable_key = (inner, stable)
            prefix_lines = self._stable_markdown_cache.get(stable_key)
            if prefix_lines is None:
                prefix_lines = renderer(stable[:-1], inner)
                self._stable_markdown_cache[stable_key] = prefix_lines
                if len(self._stable_markdown_cache) > 8:
                    self._stable_markdown_cache.pop(next(iter(self._stable_markdown_cache)))
            tail = body[len(stable) :]
            parsed = [*prefix_lines, *renderer(tail, inner)] if tail else prefix_lines
        else:
            parsed = renderer(body, inner)
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
