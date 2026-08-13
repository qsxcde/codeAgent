"""app/tui/textual_backend.py:textual 实现 TuiBackend 端口(引擎 1)。

设计(design D1/D2/D5/D6):
- 把组件产出的 ``RichLine``(样式标签段)渲染为 Rich ``Text``(标签→色值,
  含 ``user_bg`` 背景)——用 Text 对象而非 markup 字符串,规避字面量 ``[`` 被解析;
- 布局重构为终端 Dock(design D1):transcript → TopSeparator → 单行 composer →
  BottomSeparator → 状态栏 → 双端 footer;composer 固定高度一行,上下细分隔线,
  聚焦仅换 ``❯`` 提示符颜色(不再整框高亮);
- ``set_status`` / ``set_footer`` 契约升级为 ``RichLine``(design D5);
- transcript 区点击 → ``on_click(相对行号)``,经 ``TuiApp`` 查 ``block_at`` 实现
  工具折叠切换(design D4);Esc / Ctrl+Q 走应用层键事件(design D5)。
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import App
from textual.containers import Horizontal
from textual.events import Click, Resize
from textual.widgets import Input, Label, Rule, Static

from codeagent.app.tui.backend import (
    ClickHandler,
    InterruptHandler,
    ResizeHandler,
    SubmitHandler,
    TuiBackend,
)
from codeagent.app.tui.components import RichLine
from codeagent.app.tui.theme import ACCENT, BORDER_MUTED, PALETTE


def _color(tag: str | None) -> str | None:
    return PALETTE.get(tag) if tag else None


def _line_to_text(line: RichLine) -> Text:
    text = Text()
    for span in line:
        text.append(
            span.text,
            style=Style(color=_color(span.fg), bgcolor=_color(span.bg)),
        )
    return text


def rich_to_text(lines: list[RichLine]) -> Text:
    """把多行 RichLine 渲染为单块 Rich Text(行间换行)。"""
    text = Text()
    for i, line in enumerate(lines):
        text.append(_line_to_text(line))
        if i < len(lines) - 1:
            text.append("\n")
    return text


class _Transcript(Static):
    """显示组件渲染行、转发点击的 transcript widget。"""

    def on_click(self, event: Click) -> None:
        self._backend._notify_click(event.y)


class _Composer(Horizontal):
    """单行 composer:``❯`` prompt + Input 同行(design D1)。

    - 固定高度 1 行,不再占剩余布局;上下由 Top/BottomSeparator 细线区隔;
    - Input 去掉默认边框(无边框高亮),聚焦态只换 prompt 颜色。
    """

    def __init__(self, placeholder: str = "") -> None:
        super().__init__()
        self.styles.height = 1
        self.prompt = Label("❯", id="prompt")
        self.prompt.styles.width = 2
        self.prompt.styles.color = _color(BORDER_MUTED) or "gray"
        self.input = Input(placeholder=placeholder, id="input")
        # Input 官方 compact 变体:无边框 + 高度 1(composer 上下由分隔线区隔,D1)。
        self.input.compact = True

    def compose(self):
        yield self.prompt
        yield self.input

    def on_focus(self) -> None:
        self.prompt.styles.color = _color(ACCENT) or "cyan"

    def on_blur(self) -> None:
        self.prompt.styles.color = _color(BORDER_MUTED) or "gray"


class _TextualApp(App):
    """承载 transcript / 单行 composer / 状态栏 / 双端 footer 的 textual App。

    纵向 Dock(design D1):transcript(1fr)→ 细分隔线 → composer(1 行)→
    细分隔线 → 状态栏 → footer。状态栏与 footer 各占一行,位于分隔线之下。
    """

    BINDINGS = [
        ("escape", "interrupt_or_exit", "打断/退出"),
        ("ctrl+q", "interrupt_or_exit", "退出"),
    ]

    def __init__(self, backend: "TextualBackend") -> None:
        super().__init__()
        self._backend = backend
        self.transcript = _Transcript("", markup=False)
        self.transcript._backend = backend
        self.transcript.styles.height = "1fr"  # transcript 占满剩余纵向空间
        self.top_sep = Rule(orientation="horizontal")
        self.top_sep.styles.color = _color(BORDER_MUTED) or "gray"
        self.composer = _Composer(placeholder="输入消息,Enter 发送;Esc 打断/退出")
        self.bottom_sep = Rule(orientation="horizontal")
        self.bottom_sep.styles.color = _color(BORDER_MUTED) or "gray"
        self.status = Label("", id="status")
        self.footer = Label("", id="footer")

    def compose(self):
        yield self.transcript
        yield self.top_sep
        yield self.composer
        yield self.bottom_sep
        yield self.status
        yield self.footer

    def on_mount(self) -> None:
        self.composer.input.focus()
        # 首次渲染(等布局尺寸稳定后触发 resize 处理器)。
        self.call_after_refresh(self._backend._notify_resize)

    def on_resize(self, event: Resize) -> None:
        self._backend._notify_resize()

    def action_interrupt_or_exit(self) -> None:
        self._backend._notify_interrupt()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        self._backend._notify_submit(message.value)
        self.composer.input.value = ""


class TextualBackend:
    """把 ``TuiBackend`` 端口映射到 textual App 的实现。"""

    def __init__(self) -> None:
        self._app = _TextualApp(self)
        self._submit_handler: SubmitHandler | None = None
        self._interrupt_handler: InterruptHandler | None = None
        self._resize_handler: ResizeHandler | None = None
        self._click_handler: ClickHandler | None = None
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

    def render(self, lines: list[RichLine]) -> None:
        self._app.transcript.update(rich_to_text(lines))

    def set_status(self, line: RichLine) -> None:
        self._app.status.update(_line_to_text(line))

    def set_footer(self, line: RichLine) -> None:
        self._app.footer.update(_line_to_text(line))

    def on_submit(self, handler: SubmitHandler) -> None:
        self._submit_handler = handler

    def on_interrupt(self, handler: InterruptHandler) -> None:
        self._interrupt_handler = handler

    def on_resize(self, handler: ResizeHandler) -> None:
        self._resize_handler = handler

    def on_click(self, handler: ClickHandler) -> None:
        self._click_handler = handler

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

    def _notify_click(self, row: int) -> None:
        if self._click_handler is not None:
            self._click_handler(row)
