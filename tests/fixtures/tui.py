"""TUI 交互测试资源,不依赖 Textual 终端。"""

from __future__ import annotations

from typing import Any


class FakeBackend:
    """记录 TUI 渲染、输入、状态和退出行为的最小后端。"""

    def __init__(self) -> None:
        self.renders: list[Any] = []
        self.statuses: list[Any] = []
        self.footers: list[Any] = []
        self.submit = None
        self.interrupt = None
        self.quit = None
        self.resize = None
        self.click = None
        self.input_changed = None
        self.suggestion_nav = None
        self.suggestion_confirm = None
        self.scroll = None
        self.confirmation_response = None
        self.confirmation_lines: list[Any] = []
        self.suggestion_lines: list[Any] = []
        self.input_texts: list[str] = []
        self.mask_calls: list[bool] = []
        self.placeholders: list[str] = []
        self.exited: list[str] | None = None

    def run(self) -> None:  # pragma: no cover - stub
        pass

    def transcript_size(self) -> tuple[int, int]:
        return 60, 10

    def render(self, lines) -> None:
        self.renders.append(list(lines))

    def set_status(self, line) -> None:
        self.statuses.append(line)

    def set_suggestions(self, lines) -> None:
        self.suggestion_lines.append(list(lines) if lines else [])

    def set_input_text(self, text: str) -> None:
        self.input_texts.append(text)

    def set_input_mask(self, masked: bool) -> None:
        self.mask_calls.append(masked)

    def set_input_placeholder(self, text: str) -> None:
        self.placeholders.append(text)

    def on_submit(self, handler) -> None:
        self.submit = handler

    def on_interrupt(self, handler) -> None:
        self.interrupt = handler

    def on_quit(self, handler) -> None:
        self.quit = handler

    def on_resize(self, handler) -> None:
        self.resize = handler

    def on_click(self, handler) -> None:
        self.click = handler

    def on_input_changed(self, handler) -> None:
        self.input_changed = handler

    def on_suggestion_navigate(self, handler) -> None:
        self.suggestion_nav = handler

    def on_suggestion_confirm(self, handler) -> None:
        self.suggestion_confirm = handler

    def on_scroll(self, handler) -> None:
        self.scroll = handler

    def set_confirmation(self, lines) -> None:
        self.confirmation_lines.append(list(lines) if lines else [])

    def on_confirmation_response(self, handler) -> None:
        self.confirmation_response = handler

    def exit_document(self, lines: list[str]) -> None:
        self.exited = list(lines)

    def stop(self) -> None:  # pragma: no cover - stub
        pass
