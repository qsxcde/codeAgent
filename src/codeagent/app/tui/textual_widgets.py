"""Textual backend 的输入、记录区与 composer 小部件。"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.events import Click, Key, MouseScrollDown, MouseScrollUp
from textual.message import Message
from textual.widgets import Input, Label, Rule, Static, TextArea

_WHEEL_LINES = 3
_LOGIN_ACCENT = "#39d9ff"
_LOGIN_SURFACE = "#171a1d"
_LOGIN_HINT = "Enter 保存  ·  Esc 取消"
_COMPOSER_RULE = "#5a5a5a"


class InputSubmitted(Message):
    """多行或掩码输入区提交的原始文本。"""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class _InputArea(TextArea):
    """多行输入区，负责提交、换行与补全/确认键分派。"""

    BINDINGS = [
        Binding("enter", "submit", "发送", show=False, priority=True),
        Binding("shift+enter", "insert_newline", "换行", show=False, priority=True),
        Binding("ctrl+j", "insert_newline", "换行", show=False, priority=True),
        Binding("up", "suggest_up", "上一条建议", show=False, priority=True),
        Binding("down", "suggest_down", "下一条建议", show=False, priority=True),
        Binding("tab", "suggest_tab", "补全/切换焦点", show=False, priority=True),
    ]

    def __init__(self, backend: Any, placeholder: str = "") -> None:
        super().__init__(compact=True, highlight_cursor_line=False, placeholder=placeholder)
        self._backend = backend

    def action_submit(self) -> None:
        if self._backend.suggestions_active:
            self._backend._notify_suggestion_confirm()
            return
        if self.text.strip():
            self.post_message(InputSubmitted(self.text))
        self.text = ""
        self.move_cursor(self.document.end)

    def action_insert_newline(self) -> None:
        self.insert("\n")

    def action_suggest_up(self) -> None:
        if self._backend.suggestions_active:
            self._backend._notify_suggestion_navigate(-1)
        else:
            self.action_cursor_up()

    def action_suggest_down(self) -> None:
        if self._backend.suggestions_active:
            self._backend._notify_suggestion_navigate(1)
        else:
            self.action_cursor_down()

    def action_suggest_tab(self) -> None:
        if self._backend.suggestions_active:
            self._backend._notify_suggestion_confirm()
        else:
            self.screen.focus_next()

    def on_key(self, event: Key) -> None:
        if not self._backend.confirmation_active:
            return
        if event.key == "y":
            event.stop()
            self._backend._notify_confirmation_response(True)
        elif event.key == "n":
            event.stop()
            self._backend._notify_confirmation_response(False)


class _KeyInput(Input):
    """登录用原生 password 输入，提交时仍传递原文。"""

    def __init__(self, placeholder: str = "") -> None:
        super().__init__(password=True, placeholder=placeholder)

    def action_submit(self) -> None:
        if self.value.strip():
            self.post_message(InputSubmitted(self.value))
        self.value = ""


class _Transcript(Static):
    """显示渲染结果，并向 backend 转发点击和滚动。"""

    def __init__(self, backend: Any) -> None:
        super().__init__("", markup=False)
        self._backend = backend

    def on_click(self, event: Click) -> None:
        self._backend._notify_click(event.y)

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        self._backend._notify_scroll(_WHEEL_LINES)
        event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        self._backend._notify_scroll(-_WHEEL_LINES)
        event.stop()


class _Composer(VerticalGroup):
    """组合普通输入、登录掩码输入、确认条与补全建议。"""

    MAX_HEIGHT = 4

    def __init__(self, backend: Any, placeholder: str = "") -> None:
        super().__init__()
        self._backend = backend
        self.styles.height = 3
        self.top_rule, self.bottom_rule = Rule(id="composer-top-rule"), Rule(id="composer-bottom-rule")
        for rule in (self.top_rule, self.bottom_rule):
            rule.styles.margin, rule.styles.color = 0, _COMPOSER_RULE
        self.confirmation, self.suggestions = Static("", id="confirmation"), Static("", id="suggestions")
        self.confirmation.styles.height = self.suggestions.styles.height = 0
        self.input_row, self.prompt = HorizontalGroup(id="composer-input-row"), Label("›", id="prompt")
        self.prompt.styles.width, self.prompt.styles.color = 2, "#8a8a8a"
        self.login_label = Label("KEY", id="login-label")
        self.login_label.styles.width, self.login_label.styles.color, self.login_label.display = 6, _LOGIN_ACCENT, False
        self.input = _InputArea(backend, placeholder=placeholder)
        self.input.soft_wrap, self.input.show_line_numbers, self.input.styles.height = True, False, 1
        self.key_input = _KeyInput()
        self.key_input.styles.height, self.key_input.styles.background = 1, _LOGIN_SURFACE
        self.key_input.styles.border, self.key_input.styles.padding = ("none", _LOGIN_SURFACE), (0, 1)
        self.key_input.styles.color, self.key_input.display = "#f1f5f9", False
        self.login_hint = Static(_LOGIN_HINT, id="login-hint")
        self.login_hint.styles.height, self.login_hint.display = 0, False
        self.login_hint.styles.padding, self.login_hint.styles.color = (0, 0, 0, 8), "#8a9198"
        self._normal_placeholder, self._input_lines = placeholder, 1

    def compose(self) -> ComposeResult:
        yield self.top_rule
        yield self.confirmation
        yield self.suggestions
        with self.input_row:
            yield self.prompt
            yield self.login_label
            yield self.input
            yield self.key_input
        yield self.login_hint
        yield self.bottom_rule

    def set_mask(self, masked: bool, placeholder: str = "") -> None:
        if masked:
            self.key_input.placeholder, self.key_input.value = placeholder, ""
            self.key_input.display, self.input.display, self.login_label.display = True, False, True
            self.login_hint.display, self.login_hint.styles.height = True, 1
            self.top_rule.styles.color = self.bottom_rule.styles.color = _LOGIN_ACCENT
            self.key_input.focus()
        else:
            self.input.display, self.key_input.display, self.login_label.display = True, False, False
            self.login_hint.display, self.login_hint.styles.height = False, 0
            self.top_rule.styles.color = self.bottom_rule.styles.color = _COMPOSER_RULE
            self.input.placeholder = self._normal_placeholder
            self.input.focus()
        self._refresh_height()

    def _refresh_height(self) -> None:
        lines = min(self.MAX_HEIGHT, max(1, self._input_lines, self.input.virtual_size.height))
        self.input.styles.height = lines
        self.styles.height = lines + 2 + sum(
            int(widget.styles.height.value)
            for widget in (self.confirmation, self.suggestions, self.login_hint)
        )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._input_lines = event.text_area.document.line_count
        self._refresh_height()
        self.call_after_refresh(self._refresh_height)
        self._backend._notify_input_changed(event.text_area.text)
