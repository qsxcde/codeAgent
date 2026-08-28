"""Textual 的 ``TuiBackend`` 端口外观与生命周期适配。"""

from __future__ import annotations

from collections.abc import Iterable

from codeagent.app.tui.backend import (
    ClickHandler,
    ConfirmationResponseHandler,
    InputChangedHandler,
    InterruptHandler,
    QuitHandler,
    ResizeHandler,
    ScrollHandler,
    SubmitHandler,
    SuggestionConfirmHandler,
    SuggestionNavHandler,
)
from codeagent.app.tui.primitives import RichLine
from codeagent.app.tui.textual_app import _TextualApp
from codeagent.app.tui.textual_rich import _NoDefaultBackground, _line_to_text, _strip_default_bg, rich_to_text
from codeagent.app.tui.textual_widgets import _KeyInput


class TextualBackend:
    """把应用后端端口映射至 Textual App。"""

    def __init__(self) -> None:
        self._app = _TextualApp(self)
        self._submit_handler: SubmitHandler | None = None
        self._interrupt_handler: InterruptHandler | None = None
        self._quit_handler: QuitHandler | None = None
        self._resize_handler: ResizeHandler | None = None
        self._click_handler: ClickHandler | None = None
        self._input_changed_handler: InputChangedHandler | None = None
        self._suggestion_nav_handler: SuggestionNavHandler | None = None
        self._suggestion_confirm_handler: SuggestionConfirmHandler | None = None
        self._scroll_handler: ScrollHandler | None = None
        self._confirmation_handler: ConfirmationResponseHandler | None = None
        self._exit_lines: Iterable[str] | None = None
        self.suggestions_active = False
        self.confirmation_active = False

    def run(self) -> None:
        try:
            self._app.run()
        finally:
            if self._exit_lines is not None:
                for line in self._exit_lines:
                    print(line)
                print()

    def transcript_size(self) -> tuple[int, int]:
        return self._app.transcript.size.width, self._app.transcript.size.height

    def render(self, lines: list[RichLine]) -> None:
        self._app.transcript.update(rich_to_text(lines))

    def set_status(self, line: RichLine) -> None:
        self._app.status.update(_line_to_text(line))

    def set_suggestions(self, lines: list[RichLine]) -> None:
        self.suggestions_active = bool(lines)
        self._set_composer_lines("suggestions", lines)

    def set_confirmation(self, lines: list[RichLine] | None) -> None:
        self.confirmation_active = bool(lines)
        self._set_composer_lines("confirmation", lines or [])

    def _set_composer_lines(self, name: str, lines: list[RichLine]) -> None:
        widget = getattr(self._app.composer, name)
        widget.update(rich_to_text(lines) if lines else "")
        widget.styles.height = len(lines)
        self._app.composer._refresh_height()

    def set_input_text(self, text: str) -> None:
        self._app.composer.input.text = text
        self._app.composer.input.move_cursor(self._app.composer.input.document.end)

    def set_input_mask(self, masked: bool) -> None:
        self._app.composer.set_mask(masked)

    def set_input_placeholder(self, text: str) -> None:
        self._app.composer.key_input.placeholder = text

    def on_submit(self, handler: SubmitHandler) -> None:
        self._submit_handler = handler

    def on_interrupt(self, handler: InterruptHandler) -> None:
        self._interrupt_handler = handler

    def on_quit(self, handler: QuitHandler) -> None:
        self._quit_handler = handler

    def on_resize(self, handler: ResizeHandler) -> None:
        self._resize_handler = handler

    def on_click(self, handler: ClickHandler) -> None:
        self._click_handler = handler

    def on_input_changed(self, handler: InputChangedHandler) -> None:
        self._input_changed_handler = handler

    def on_suggestion_navigate(self, handler: SuggestionNavHandler) -> None:
        self._suggestion_nav_handler = handler

    def on_suggestion_confirm(self, handler: SuggestionConfirmHandler) -> None:
        self._suggestion_confirm_handler = handler

    def on_scroll(self, handler: ScrollHandler) -> None:
        self._scroll_handler = handler

    def on_confirmation_response(self, handler: ConfirmationResponseHandler) -> None:
        self._confirmation_handler = handler

    def exit_document(self, lines: Iterable[str]) -> None:
        self._exit_lines = lines
        self._app.exit()

    def stop(self) -> None:
        self._app.exit()

    def _notify_submit(self, text: str) -> None:
        if self._submit_handler is not None:
            self._submit_handler(text)

    def _notify_quit(self) -> None:
        if self._quit_handler is not None:
            self._quit_handler()

    def _notify_interrupt(self) -> None:
        if self._interrupt_handler is not None:
            self._interrupt_handler()

    def _notify_resize(self) -> None:
        if self._resize_handler is not None:
            self._resize_handler()

    def _notify_click(self, row: int) -> None:
        if self._click_handler is not None:
            self._click_handler(row)

    def _notify_input_changed(self, text: str) -> None:
        if self._input_changed_handler is not None:
            self._input_changed_handler(text)

    def _notify_suggestion_navigate(self, delta: int) -> None:
        if self._suggestion_nav_handler is not None:
            self._suggestion_nav_handler(delta)

    def _notify_suggestion_confirm(self) -> None:
        if self._suggestion_confirm_handler is not None:
            self._suggestion_confirm_handler()

    def _notify_scroll(self, delta: int) -> None:
        if self._scroll_handler is not None:
            self._scroll_handler(delta)

    def _notify_confirmation_response(self, approved: bool) -> None:
        if self._confirmation_handler is not None:
            self._confirmation_handler(approved)
