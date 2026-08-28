"""Textual 应用壳：只负责布局、键位和 backend 回调转发。"""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Resize
from textual.widgets import Label

from codeagent.app.tui.textual_rich import _NoDefaultBackground
from codeagent.app.tui.textual_widgets import InputSubmitted, _Composer, _Transcript

_LOGIN_SURFACE = "#171a1d"


class _TextualApp(App):
    BINDINGS = [
        Binding("escape", "interrupt", "打断", show=False),
        Binding("ctrl+c", "quit", "退出", show=False, priority=True),
        Binding("ctrl+q", "quit", "退出", show=False, priority=True),
        Binding("pageup", "page_up", "上翻页", show=False, priority=True),
        Binding("pagedown", "page_down", "下翻页", show=False, priority=True),
    ]

    def __init__(self, backend: Any) -> None:
        super().__init__()
        self._backend = backend
        self.transcript = _Transcript(backend)
        self.transcript.styles.height = "1fr"
        self.composer = _Composer(backend, placeholder="输入消息...")
        self.status = Label("", id="status")

    def compose(self) -> ComposeResult:
        yield self.transcript
        yield self.composer
        yield self.status

    def on_mount(self) -> None:
        self._filters.insert(0, _NoDefaultBackground())
        self.styles.background = self.screen.styles.background = "ansi_default"
        self.transcript.styles.background = self.composer.input.styles.background = "ansi_default"
        self.composer.key_input.styles.background = _LOGIN_SURFACE
        self.composer.input.focus()
        self.call_after_refresh(self._backend._notify_resize)

    def on_resize(self, event: Resize) -> None:
        self._backend._notify_resize()

    def action_interrupt(self) -> None:
        self._backend._notify_interrupt()

    def action_quit(self) -> None:
        self._backend._notify_quit()

    def action_page_up(self) -> None:
        self._backend._notify_scroll(self._page_delta())

    def action_page_down(self) -> None:
        self._backend._notify_scroll(-self._page_delta())

    def _page_delta(self) -> int:
        return max(1, self.transcript.size.height - 1)

    def on_input_submitted(self, message: InputSubmitted) -> None:
        self._backend._notify_submit(message.text)
