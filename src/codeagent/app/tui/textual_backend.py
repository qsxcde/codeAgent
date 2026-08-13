"""app/tui/textual_backend.py:textual 实现 TuiBackend 端口(引擎 1)。

设计(design D1/D7):textual 只负责 alt 屏 + 行渲染 + 输入原语;transcript 是
一个「显示行」Static widget(内容是我们组件渲染出的行,``markup=False`` 按字面量
显示),不映射成 textual 原生 widget 树——保持组件纯 ``render(width)``,端口语义
干净。Esc / Ctrl+Q 走应用层键事件,不走终端信号(design D5)。

布局(design D8):transcript 占满剩余纵向空间(``height: 1fr``),状态栏/输入框/
底部提示固定在底部。
"""

from __future__ import annotations

from textual.app import App
from textual.events import Resize
from textual.widgets import Input, Label, Static

from codeagent.app.tui.backend import (
    InterruptHandler,
    ResizeHandler,
    SubmitHandler,
    TuiBackend,
)


class _TextualApp(App):
    """承载 transcript 行 / 状态栏 / 输入框 / 底部提示的 textual App。"""

    BINDINGS = [
        ("escape", "interrupt_or_exit", "打断/退出"),
        ("ctrl+q", "interrupt_or_exit", "退出"),
    ]

    def __init__(self, backend: "TextualBackend") -> None:
        super().__init__()
        self._backend = backend
        self.transcript = Static("", markup=False)
        self.transcript.styles.height = "1fr"  # transcript 占满剩余纵向空间
        self.status = Label("[IDLE]", id="status")
        self.input = Input(placeholder="输入消息,Enter 发送;Esc 打断/退出", id="input")
        self.footer = Label("Esc 打断/退出", id="footer")

    def compose(self):
        yield self.transcript
        yield self.status
        yield self.input
        yield self.footer

    def on_mount(self) -> None:
        self.input.focus()
        # 首次渲染(等布局尺寸稳定后触发 resize 处理器)。
        self.call_after_refresh(self._backend._notify_resize)

    def on_resize(self, event: Resize) -> None:
        self._backend._notify_resize()

    def action_interrupt_or_exit(self) -> None:
        self._backend._notify_interrupt()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        self._backend._notify_submit(message.value)
        self.input.value = ""


class TextualBackend:
    """把 ``TuiBackend`` 端口映射到 textual App 的实现。"""

    def __init__(self) -> None:
        self._app = _TextualApp(self)
        self._submit_handler: SubmitHandler | None = None
        self._interrupt_handler: InterruptHandler | None = None
        self._resize_handler: ResizeHandler | None = None
        self._exit_lines: list[str] | None = None

    # -- 端口实现 ----------------------------------------------------------

    def run(self) -> None:
        try:
            self._app.run()
        finally:
            # 主屏已恢复后打印完整文档(design D5:退出文档 = 逻辑完整,非最后一屏)。
            if self._exit_lines is not None:
                print("\n".join(self._exit_lines))
                print()

    def transcript_size(self) -> tuple[int, int]:
        width = self._app.transcript.size.width
        height = self._app.transcript.size.height
        return width, height

    def render(self, lines: list[str]) -> None:
        self._app.transcript.update("\n".join(lines))

    def set_status(self, text: str) -> None:
        self._app.status.update(text)

    def set_footer(self, text: str) -> None:
        self._app.footer.update(text)

    def on_submit(self, handler: SubmitHandler) -> None:
        self._submit_handler = handler

    def on_interrupt(self, handler: InterruptHandler) -> None:
        self._interrupt_handler = handler

    def on_resize(self, handler: ResizeHandler) -> None:
        self._resize_handler = handler

    def exit_document(self, lines: list[str]) -> None:
        self._exit_lines = lines
        self._app.exit()

    def stop(self) -> None:
        self._app.exit()

    # -- App 回调 ----------------------------------------------------------

    def _notify_submit(self, text: str) -> None:
        if self._submit_handler is not None:
            self._submit_handler(text)

    def _notify_interrupt(self) -> None:
        if self._interrupt_handler is not None:
            self._interrupt_handler()

    def _notify_resize(self) -> None:
        if self._resize_handler is not None:
            self._resize_handler()
