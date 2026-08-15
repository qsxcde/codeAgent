"""app/tui/textual_backend.py:textual 实现 TuiBackend 端口(引擎 1)。

设计(design D1/D2/D5/D6):
- 把组件产出的 ``RichLine``(样式标签段)渲染为 Rich ``Text``(标签→色值,
  含 ``user_bg`` 背景)——用 Text 对象而非 markup 字符串,规避字面量 ``[`` 被解析;
- 布局重构为终端 Dock(design D1):transcript → TopSeparator → 多行 composer →
  BottomSeparator → 单行状态栏;composer 为多行输入(1~4 行自动增高,超出内部
  滚动),Enter 提交、Shift+Enter 换行、Tab 切换焦点(Esc 冒泡到应用层打断/退出);
- ``set_status`` 契约升级为 ``RichLine``(design D5);
- transcript 区点击 → ``on_click(相对行号)``,经 ``TuiApp`` 查 ``block_at`` 实现
  工具折叠切换(design D4);Esc / Ctrl+Q 走应用层键事件(design D5)。
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.events import Click, Resize
from textual.message import Message
from textual.widgets import Label, Static, TextArea

from codeagent.app.tui.backend import (
    ClickHandler,
    InputChangedHandler,
    InterruptHandler,
    ResizeHandler,
    SubmitHandler,
    SuggestionConfirmHandler,
    SuggestionNavHandler,
)
from codeagent.app.tui.components import RichLine
from codeagent.app.tui.theme import PALETTE


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


class InputSubmitted(Message):
    """多行输入区提交消息(Enter)。"""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class _InputArea(TextArea):
    """多行输入区:Enter 提交、Shift+Enter 换行、补全键位拦截(T-45)。

    - 补全激活时(backend 记录):↑/↓ 导航建议、Enter/Tab 确认填入、Esc 收起;
    - 补全未激活:↑/↓ 恢复输入框光标移动、Tab 原生焦点切换、Enter 提交;
    - ``tab_behavior`` 保持默认 focus:Esc 不被吞,可冒泡到应用层打断/退出。
    """

    BINDINGS = [
        Binding("enter", "submit", "发送", show=False, priority=True),
        Binding("shift+enter", "insert_newline", "换行", show=False, priority=True),
        Binding("up", "suggest_up", "上一条建议", show=False, priority=True),
        Binding("down", "suggest_down", "下一条建议", show=False, priority=True),
        Binding("tab", "suggest_tab", "补全/切换焦点", show=False, priority=True),
    ]

    def __init__(self, backend: "TextualBackend", placeholder: str = "") -> None:
        super().__init__(
            compact=True,
            highlight_cursor_line=False,
            placeholder=placeholder,
        )
        self._backend = backend

    def action_submit(self) -> None:
        if self._backend.suggestions_active:
            self._backend._notify_suggestion_confirm()
            return
        text = self.text
        if text.strip():
            self.post_message(InputSubmitted(text))
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

class _Transcript(Static):
    """显示组件渲染行、转发点击的 transcript widget。"""

    def on_click(self, event: Click) -> None:
        self._backend._notify_click(event.y)


class _Composer(VerticalGroup):
    """Codex 风格 composer:无边框的深灰输入条 + 补全建议条(T-45)。

    - 高度自适应:行数 1..MAX_HEIGHT,超出后内部滚动(不占剩余布局);
    - 默认只显示 ``›``、占位文字和光标，不显示外框或快捷键说明;
    - Enter 提交 / Shift+Enter 换行(见 ``_InputArea``);
    - suggestions 为输入框上方的补全建议条(空 = 高度 0 隐藏)。
    """

    #: 输入区最大高度(行);超出后 TextArea 内部滚动。
    MAX_HEIGHT = 4

    def __init__(self, backend: "TextualBackend", placeholder: str = "") -> None:
        super().__init__()
        self._backend = backend
        self.styles.height = 3
        self.styles.background = "#2b2b2b"
        self.styles.padding = (1, 0)
        self.suggestions = Static("", id="suggestions")
        self.suggestions.styles.height = 0  # 默认隐藏
        self.input_row = HorizontalGroup(id="composer-input-row")
        self.prompt = Label("›", id="prompt")
        self.prompt.styles.width = 2
        self.prompt.styles.color = "#8a8a8a"
        self.input = _InputArea(backend, placeholder=placeholder)
        self.input.soft_wrap = True
        self.input.show_line_numbers = False
        self.input.styles.height = 1
        self.input.styles.background = "#2b2b2b"
        # 输入行数缓存:_refresh_height 可在无事件上下文(set_suggestions 路径)使用。
        self._input_lines = 1

    def compose(self):
        yield self.suggestions
        with self.input_row:
            yield self.prompt
            yield self.input

    def _refresh_height(self) -> None:
        """高度自适应:输入行数 1..MAX_HEIGHT + 呼吸空间 + 建议条行数(D3)。

        建议条显示时计入其高度,避免输入行被固定高度裁剪(视觉测试缺陷)。
        输入行数取缓存值,本方法在 set_suggestions 路径也可安全调用。
        """
        lines = min(self.MAX_HEIGHT, max(1, self._input_lines))
        self.input.styles.height = lines
        suggest = int(self.suggestions.styles.height.value)
        # 默认一行文字上下各留一行空白；内容增长时保留同样的呼吸空间。
        self.styles.height = lines + 2 + suggest

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """高度自适应与输入变更通知(见 ``_refresh_height``)。"""
        self._input_lines = event.text_area.document.line_count
        self._refresh_height()
        # 输入变化通知视图:计算补全建议(T-45)。
        self._backend._notify_input_changed(event.text_area.text)


class _TextualApp(App):
    """承载 transcript / 多行 composer / 单行状态栏的 textual App。

    纵向 Dock:transcript(1fr)→ 无边框 composer(1~4 行)→ 单行状态栏。
    状态栏为单行会话元信息(模型、思考强度与工作目录)。
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
        self.composer = _Composer(backend, placeholder="输入消息...")
        self.status = Label("", id="status")

    def compose(self):
        yield self.transcript
        yield self.composer
        yield self.status

    def on_mount(self) -> None:
        self.composer.input.focus()
        # 首次渲染(等布局尺寸稳定后触发 resize 处理器)。
        self.call_after_refresh(self._backend._notify_resize)

    def on_resize(self, event: Resize) -> None:
        self._backend._notify_resize()

    def action_interrupt_or_exit(self) -> None:
        self._backend._notify_interrupt()

    def on_input_submitted(self, message: InputSubmitted) -> None:
        self._backend._notify_submit(message.text)


class TextualBackend:
    """把 ``TuiBackend`` 端口映射到 textual App 的实现。"""

    def __init__(self) -> None:
        self._app = _TextualApp(self)
        self._submit_handler: SubmitHandler | None = None
        self._interrupt_handler: InterruptHandler | None = None
        self._resize_handler: ResizeHandler | None = None
        self._click_handler: ClickHandler | None = None
        self._input_changed_handler: InputChangedHandler | None = None
        self._suggestion_nav_handler: SuggestionNavHandler | None = None
        self._suggestion_confirm_handler: SuggestionConfirmHandler | None = None
        self._exit_lines: list[str] | None = None
        #: 补全浮层激活态:引擎层据此分派 ↑/↓/Tab/Enter(见 _InputArea)。
        self.suggestions_active = False

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

    def set_suggestions(self, lines: list[RichLine]) -> None:
        """更新补全建议条(空列表 = 隐藏;激活态供输入区键位分派)。

        建议条高度变化后同步刷新 composer 高度,输入行不被裁剪(D3)。
        """
        self.suggestions_active = bool(lines)
        if lines:
            self._app.composer.suggestions.update(rich_to_text(lines))
            self._app.composer.suggestions.styles.height = len(lines)
        else:
            self._app.composer.suggestions.update("")
            self._app.composer.suggestions.styles.height = 0
        self._app.composer._refresh_height()

    def set_input_text(self, text: str) -> None:
        """替换输入框全文(建议确认填入)并把光标移到末尾。"""
        self._app.composer.input.text = text
        self._app.composer.input.move_cursor(self._app.composer.input.document.end)

    def on_submit(self, handler: SubmitHandler) -> None:
        self._submit_handler = handler

    def on_interrupt(self, handler: InterruptHandler) -> None:
        self._interrupt_handler = handler

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
        # 补全浮层激活时 Esc 先收起浮层,不触发打断/退出(T-45)。
        if self.suggestions_active:
            self.set_suggestions([])
            return
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
