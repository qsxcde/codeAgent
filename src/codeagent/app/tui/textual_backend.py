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

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.color import Color
from textual.containers import HorizontalGroup, VerticalGroup
from textual.events import Click, Key, MouseScrollDown, MouseScrollUp, Resize
from textual.filter import LineFilter
from textual.message import Message
from textual.widgets import Input, Label, Rule, Static, TextArea

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
from codeagent.app.tui.components import RichLine
from codeagent.app.tui.theme import BOLD, PALETTE

#: 滚轮每格对应的行数(终端惯例:一个齿 ≈ 3 行)。
_WHEEL_LINES = 3

#: 登录输入态的视觉令牌:与普通 composer 的终端融合背景保持区分,
#: 但不使用 Textual Input 默认的高亮焦点边框。
_LOGIN_ACCENT = "#39d9ff"
_LOGIN_SURFACE = "#171a1d"
_LOGIN_HINT = "Enter 保存  ·  Esc 取消"
_COMPOSER_RULE = "#5a5a5a"


def _strip_default_bg(style: Style) -> Style:
    """重建 Style,仅去掉 default 背景(Style 不可变,无 setter)。"""
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
    """剥离 Rich default 背景,使其落到终端默认背景(背景融合)。

    Textual 的 ANSIToTruecolor 过滤器把 default 背景映射为主题实色
    (rgb(12,12,12)),导致全屏不透明;本过滤器插在其之前,把 default
    背景的样式重建为无背景,显式色值背景原样透传。
    """

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


def _color(tag: str | None) -> str | None:
    return PALETTE.get(tag) if tag else None


def _line_to_text(line: RichLine) -> Text:
    text = Text()
    for span in line:
        text.append(
            span.text,
            style=Style(
                color=_color(span.fg),
                bgcolor=_color(span.bg),
                bold=(span.fg == BOLD),  # bold 标签经引擎映射为字重而非色值(design T-46)
            ),
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
    """多行输入区:Enter 提交、Shift+Enter 换行、补全键位拦截(T-45)、确认键(T-40)。

    - 补全激活时(backend 记录):↑/↓ 导航建议、Enter/Tab 确认填入、Esc 收起;
    - 确认条激活时(backend 记录):y/n 归属确认条,不落入输入文本;确认未激活
      时不拦截任何按键(含粘贴/突发输入),全部走输入区原生路径——早期用
      priority 绑定常驻拦截 y/n,突发输入下 insert() 回填与原生输入竞争,
      导致字符丢失/重排(视觉测试缺陷);
    - 补全未激活:↑/↓ 恢复输入框光标移动、Tab 原生焦点切换、Enter 提交;
      换行键 Shift+Enter 依赖 kitty 键盘协议,不支持的终端改用 Ctrl+J;
    - ``tab_behavior`` 保持默认 focus:Esc 不被吞,可冒泡到应用层打断/退出。
    """

    BINDINGS = [
        Binding("enter", "submit", "发送", show=False, priority=True),
        Binding("shift+enter", "insert_newline", "换行", show=False, priority=True),
        # 兜底换行键:shift+enter 依赖 kitty 键盘协议,不支持的终端与 Enter
        # 同码;textual 又会丢弃 ESC+CR 的 ESC(alt+enter 不可达);ctrl+j(\n)
        # 在所有终端都有独立字节,恒可换行。
        Binding("ctrl+j", "insert_newline", "换行", show=False, priority=True),
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

    def on_key(self, event: Key) -> None:
        """确认条激活时 y/n 归属确认条;其余情形不触碰事件(原生输入路径)。"""
        if not self._backend.confirmation_active:
            return
        if event.key == "y":
            event.stop()
            self._backend._notify_confirmation_response(True)
        elif event.key == "n":
            event.stop()
            self._backend._notify_confirmation_response(False)

class _KeyInput(Input):
    """登录掩码输入(单行,tui-login-command):``password=True`` 原生掩码。

    - 复用 ``InputSubmitted`` 消息与普通输入同路径提交(原文取 ``value``,
      掩码只影响显示,不出现在任何渲染/日志);
    - 不绑定 Esc:冒泡到应用层,由视图在登录态优先取消;
    - 提交后清空,与 ``_InputArea.action_submit`` 行为一致。
    """

    def __init__(self, placeholder: str = "") -> None:
        super().__init__(password=True, placeholder=placeholder)

    def action_submit(self) -> None:
        text = self.value
        if text.strip():
            self.post_message(InputSubmitted(text))
        self.value = ""


class _Transcript(Static):
    """显示组件渲染行、转发点击与滚轮的 transcript widget。

    - 点击 → ``on_click(相对行号)``(design D4,工具折叠);
    - 滚轮 → ``_notify_scroll(±_WHEEL_LINES)``(design T-47);``stop()`` 防止
      事件冒泡到其它可滚动祖先,保证滚动语义唯一归属 transcript 视口。
    """

    def on_click(self, event: Click) -> None:
        self._backend._notify_click(event.y)

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        self._backend._notify_scroll(_WHEEL_LINES)
        event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        self._backend._notify_scroll(-_WHEEL_LINES)
        event.stop()


class _Composer(VerticalGroup):
    """极简 composer:上下全宽细分隔线 + 透明背景输入行(T-45/T-40)。

    - 无实色背景(与终端背景融合);上下各一条全宽 solid 分隔线;
    - 高度自适应:行数 1..MAX_HEIGHT,超出后内部滚动(不占剩余布局);
      高度 = 输入行数 + 分隔线 2 行 + 确认条/建议条行数;
    - 默认只显示 ``›``、占位文字和光标，不显示外框或快捷键说明;
    - Enter 提交 / Shift+Enter 换行(见 ``_InputArea``);
    - confirmation 为确认条(security-permissions,空 = 高度 0 隐藏),位于
      建议条之上;suggestions 为补全建议条。
    """

    #: 输入区最大高度(行);超出后 TextArea 内部滚动。
    MAX_HEIGHT = 4

    def __init__(self, backend: "TextualBackend", placeholder: str = "") -> None:
        super().__init__()
        self._backend = backend
        self.styles.height = 3
        self.top_rule = Rule(id="composer-top-rule")
        self.bottom_rule = Rule(id="composer-bottom-rule")
        for rule in (self.top_rule, self.bottom_rule):
            rule.styles.margin = 0
            rule.styles.color = "#5a5a5a"
        self.confirmation = Static("", id="confirmation")
        self.confirmation.styles.height = 0  # 默认隐藏
        self.suggestions = Static("", id="suggestions")
        self.suggestions.styles.height = 0  # 默认隐藏
        self.input_row = HorizontalGroup(id="composer-input-row")
        self.prompt = Label("›", id="prompt")
        self.prompt.styles.width = 2
        self.prompt.styles.color = "#8a8a8a"
        self.login_label = Label("KEY", id="login-label")
        self.login_label.styles.width = 6
        self.login_label.styles.color = _LOGIN_ACCENT
        self.login_label.display = False
        self.input = _InputArea(backend, placeholder=placeholder)
        self.input.soft_wrap = True
        self.input.show_line_numbers = False
        self.input.styles.height = 1
        #: 登录掩码输入(tui-login-command):常驻 compose、display 互斥切换,
        #: 初始隐藏;``_normal_placeholder`` 供退出登录态时恢复普通提示。
        self.key_input = _KeyInput()
        self.key_input.styles.height = 1
        self.key_input.styles.background = _LOGIN_SURFACE
        self.key_input.styles.border = ("none", _LOGIN_SURFACE)
        self.key_input.styles.padding = (0, 1)
        self.key_input.styles.color = "#f1f5f9"
        self.key_input.display = False
        self.login_hint = Static(_LOGIN_HINT, id="login-hint")
        self.login_hint.styles.height = 0
        self.login_hint.display = False
        self.login_hint.styles.padding = (0, 0, 0, 8)
        self.login_hint.styles.color = "#8a9198"
        self._normal_placeholder = placeholder
        # 输入行数缓存:_refresh_height 可在无事件上下文(set_suggestions 路径)使用。
        self._input_lines = 1

    def compose(self):
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
        """登录态掩码切换(tui-login-command):普通输入 ↔ 密码输入 display 互斥。

        进入:密码输入清空、显示并聚焦,提示文案就位;退出:恢复普通输入、
        提示文案还原。组件常驻避免异步 mount;焦点显式归属可见组件。
        """
        if masked:
            self.key_input.placeholder = placeholder
            self.key_input.value = ""
            self.key_input.display = True
            self.input.display = False
            self.login_label.display = True
            self.login_hint.display = True
            self.login_hint.styles.height = 1
            self.top_rule.styles.color = _LOGIN_ACCENT
            self.bottom_rule.styles.color = _LOGIN_ACCENT
            self.key_input.focus()
        else:
            self.input.display = True
            self.key_input.display = False
            self.login_label.display = False
            self.login_hint.display = False
            self.login_hint.styles.height = 0
            self.top_rule.styles.color = _COMPOSER_RULE
            self.bottom_rule.styles.color = _COMPOSER_RULE
            self.input.placeholder = self._normal_placeholder
            self.input.focus()
        self._refresh_height()

    def _refresh_height(self) -> None:
        """高度自适应:渲染行数 1..MAX_HEIGHT + 上下分隔线 + 确认条/建议条行数(D3)。

        行数取逻辑行数与软换行渲染行数(virtual_size.height)的较大者:
        单行超长输入软换行后按渲染行增高,而非固定一行高把视图滚到光标处。
        virtual_size 在布局后才更新,``on_text_area_changed`` 会在 refresh 后
        重算一次。确认条与建议条显示时计入其高度,避免输入行被裁剪(视觉测试缺陷)。
        """
        wrapped = self.input.virtual_size.height
        lines = min(self.MAX_HEIGHT, max(1, self._input_lines, wrapped))
        self.input.styles.height = lines
        confirm = int(self.confirmation.styles.height.value)
        suggest = int(self.suggestions.styles.height.value)
        login_hint = int(self.login_hint.styles.height.value)
        self.styles.height = lines + 2 + confirm + suggest + login_hint

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """高度自适应与输入变更通知(见 ``_refresh_height``)。"""
        self._input_lines = event.text_area.document.line_count
        self._refresh_height()
        # 软换行渲染行数在布局后才可得,refresh 后按 virtual_size 重算高度。
        self.call_after_refresh(self._refresh_height)
        # 输入变化通知视图:计算补全建议(T-45)。
        self._backend._notify_input_changed(event.text_area.text)


class _TextualApp(App):
    """承载 transcript / 多行 composer / 单行状态栏的 textual App。

    纵向 Dock:transcript(1fr)→ 分隔线 composer(1~4 行)→ 单行状态栏。
    状态栏为单行会话元信息(模型、思考强度与工作目录)。
    """

    BINDINGS = [
        # 收尾补丁:Esc 仅中断(不再退出);Ctrl+C 覆盖 textual 系统 help_quit 绑定
        # (priority=True 优先)承担退出;Ctrl+Q 保留为退出路径。
        Binding("escape", "interrupt", "打断", show=False),
        Binding("ctrl+c", "quit", "退出", show=False, priority=True),
        Binding("ctrl+q", "quit", "退出", show=False, priority=True),
        # 键盘滚动(T-47):priority=True 抢先于输入区,PageUp/PageDown 恒定
        # 滚动 transcript 视口(输入框 1~4 行,无整页光标移动需求)。
        Binding("pageup", "page_up", "上翻页", show=False, priority=True),
        Binding("pagedown", "page_down", "下翻页", show=False, priority=True),
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
        # 背景融合:剥离 default 背景(须先于 ANSIToTruecolor),四处背景改为
        # 终端默认背景语义;显式色值背景(用户消息块)不受影响。TextArea 主题
        # 背景为实色,须显式覆盖为终端默认背景。
        self._filters.insert(0, _NoDefaultBackground())
        self.styles.background = "ansi_default"
        self.screen.styles.background = "ansi_default"
        self.transcript.styles.background = "ansi_default"
        self.composer.input.styles.background = "ansi_default"
        self.composer.key_input.styles.background = _LOGIN_SURFACE
        self.composer.input.focus()
        # 首次渲染(等布局尺寸稳定后触发 resize 处理器)。
        self.call_after_refresh(self._backend._notify_resize)

    def on_resize(self, event: Resize) -> None:
        self._backend._notify_resize()

    def action_interrupt(self) -> None:
        """Esc:仅中断(运行中打断;空闲由视图提示退出方式,不再直接退出)。"""
        self._backend._notify_interrupt()

    def action_quit(self) -> None:
        """Ctrl+C / Ctrl+Q:退出(运行中先中止当前轮,再退出)。"""
        self._backend._notify_quit()

    def _page_delta(self) -> int:
        """一页的行数(视口高 - 1,至少 1 行;design T-47 键盘翻页)。"""
        return max(1, self.transcript.size.height - 1)

    def action_page_up(self) -> None:
        self._backend._notify_scroll(self._page_delta())

    def action_page_down(self) -> None:
        self._backend._notify_scroll(-self._page_delta())

    def on_input_submitted(self, message: InputSubmitted) -> None:
        self._backend._notify_submit(message.text)


class TextualBackend:
    """把 ``TuiBackend`` 端口映射到 textual App 的实现。"""

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
        self._exit_lines: list[str] | None = None
        #: 补全浮层激活态:引擎层据此分派 ↑/↓/Tab/Enter(见 _InputArea)。
        self.suggestions_active = False
        #: 确认条激活态:引擎层据此分派 y/n(见 _InputArea;security-permissions)。
        self.confirmation_active = False

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

    def set_input_mask(self, masked: bool) -> None:
        """切换登录掩码输入(tui-login-command):True = 密码输入(原生掩码),
        False = 恢复普通多行输入与提示。"""
        self._app.composer.set_mask(masked)

    def set_input_placeholder(self, text: str) -> None:
        """设置登录密码输入的提示文案(占位;普通输入提示在退出掩码时还原)。"""
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

    def set_confirmation(self, lines: list[RichLine] | None) -> None:
        """显示/隐藏确认条;激活态供输入区 y/n 键分派(security-permissions)。

        确认条高度变化后同步刷新 composer 高度,输入行不被裁剪(同 D3 机制)。
        """
        self.confirmation_active = bool(lines)
        if lines:
            self._app.composer.confirmation.update(rich_to_text(lines))
            self._app.composer.confirmation.styles.height = len(lines)
        else:
            self._app.composer.confirmation.update("")
            self._app.composer.confirmation.styles.height = 0
        self._app.composer._refresh_height()

    def on_confirmation_response(self, handler: ConfirmationResponseHandler) -> None:
        self._confirmation_handler = handler

    def exit_document(self, lines: list[str]) -> None:
        self._exit_lines = lines
        self._app.exit()

    def stop(self) -> None:
        self._app.exit()

    # -- App 回调 ----------------------------------------------------------

    def _notify_submit(self, text: str) -> None:
        if self._submit_handler is not None:
            self._submit_handler(text)

    def _notify_quit(self) -> None:
        if self._quit_handler is not None:
            self._quit_handler()

    def _notify_interrupt(self) -> None:
        # Esc 一律交由视图分派:浮层收起(值语境连同输入清空)/运行打断/空闲提示,
        # 引擎层不自行消费,避免与视图状态脱节(T-45 内联选择后归一)。
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
