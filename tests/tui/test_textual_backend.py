"""tests/tui/test_textual_backend.py:textual 后端渲染通道的离线断言。

textual 延迟 import(与 src 侧一致)。覆盖 fix-tui-command-completion D3:
建议条高度计入 composer,输入行不被裁剪;T-47 滚动:滚轮转发与
PageUp/PageDown 恒滚视口;确认键仅在激活时拦截;终端背景融合。
"""

import asyncio
from typing import Any

from textual.events import MouseScrollDown, MouseScrollUp


def _wheel(direction: str) -> Any:
    """构造一个滚轮事件(MouseEvent 基类构造参数较多,测试集中封装)。"""
    cls = MouseScrollDown if direction == "down" else MouseScrollUp
    return cls(None, 0, 0, 0, 3 if direction == "up" else -3, 0, False, False, False)


def test_composer_height_counts_suggestion_lines():
    """(回归:D3)_refresh_height 计入建议条行数,收起后回落。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    composer = TextualBackend()._app.composer
    base = 3  # 单行输入 + 上下呼吸空间

    assert composer.styles.height.value == base
    composer.suggestions.styles.height = 3
    composer._refresh_height()
    assert composer.styles.height.value == base + 3
    composer.suggestions.styles.height = 0
    composer._refresh_height()
    assert composer.styles.height.value == base


def test_set_suggestions_refreshes_composer_height_in_app():
    """(回归:D3)set_suggestions 接线:浮层弹出/收起同步增减 composer 高度。"""
    from codeagent.app.tui.components import Span
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        async with backend._app.run_test(size=(80, 24)):
            backend.set_suggestions([[Span("/a")], [Span("/b")]])
            assert backend._app.composer.styles.height.value == 3 + 2
            backend.set_suggestions([])
            assert backend._app.composer.styles.height.value == 3

    asyncio.run(_run())


def test_transcript_wheel_notifies_scroll():
    """滚轮上/下 → on_scroll(±3 行),事件被 stop 不冒泡(spec「滚轮滚动」)。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        scrolls: list[int] = []
        backend.on_scroll(scrolls.append)
        async with app.run_test(size=(80, 24)):
            up, down = _wheel("up"), _wheel("down")
            app.transcript.on_mouse_scroll_up(up)
            app.transcript.on_mouse_scroll_down(down)
            assert scrolls == [3, -3]
            assert up._stop_propagation and down._stop_propagation  # 不冒泡给其它滚动祖先

    asyncio.run(_run())


def test_page_keys_always_scroll_viewport():
    """PageUp/PageDown 无论输入框是否聚焦均滚动视口(spec「键盘滚动」修订)。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        scrolls: list[int] = []
        backend.on_scroll(scrolls.append)
        async with app.run_test(size=(80, 24)):
            page = max(1, app.transcript.size.height - 1)
            # on_mount 后输入框持有焦点:翻页仍归视口(此前分派给编辑区导致
            # 键盘滚动不可达,视觉测试缺陷)。
            assert app.composer.input.has_focus
            app.action_page_up()
            app.action_page_down()
            assert scrolls == [page, -page]
            app.composer.input.has_focus = False
            app.action_page_up()
            assert scrolls == [page, -page, page]

    asyncio.run(_run())


# -- 确认交互(security-permissions)-------------------------------------------


def test_set_confirmation_shows_bar_and_activates_keys():
    """set_confirmation 显示确认条并计入 composer 高度;清空后回落。"""
    from codeagent.app.tui.components import Span
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        async with backend._app.run_test(size=(80, 24)):
            assert backend.confirmation_active is False
            assert backend._app.composer.confirmation.styles.height.value == 0
            backend.set_confirmation(
                [[Span("⚠ 需要确认")], [Span("  git push")], [Span("  [y] 允许")]]
            )
            assert backend.confirmation_active is True
            assert backend._app.composer.confirmation.styles.height.value == 3
            assert backend._app.composer.styles.height.value == 3 + 3
            backend.set_confirmation(None)
            assert backend.confirmation_active is False
            assert backend._app.composer.confirmation.styles.height.value == 0
            assert backend._app.composer.styles.height.value == 3

    asyncio.run(_run())


def test_confirmation_keys_intercept_only_when_active():
    """确认激活时 y/n 被拦截(stop + 响应回调);未激活时事件不被触碰(spec「键位归属」)。"""
    from textual.events import Key

    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        responses: list[bool] = []
        backend.on_confirmation_response(responses.append)
        async with app.run_test(size=(80, 24)):
            # 未激活:y/n 事件不被 stop、无响应回调(原生输入路径,含突发序列)。
            burst = [Key(ch, ch) for ch in "banana"]
            for ev in burst:
                app.composer.input.on_key(ev)
            assert responses == []
            assert not any(ev._stop_propagation for ev in burst)

            # 激活:y/n 被 stop 并转响应;其它键不拦截。
            backend.confirmation_active = True
            y, n, other = Key("y", "y"), Key("n", "n"), Key("x", "x")
            app.composer.input.on_key(y)
            app.composer.input.on_key(n)
            app.composer.input.on_key(other)
            assert responses == [True, False]
            assert y._stop_propagation and n._stop_propagation
            assert not other._stop_propagation

    asyncio.run(_run())


def test_confirmation_response_port_wired():
    """on_confirmation_response 接线:引擎回调转发视图处理器。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        calls: list[bool] = []
        backend.on_confirmation_response(calls.append)
        backend._notify_confirmation_response(True)
        backend._notify_confirmation_response(False)
        assert calls == [True, False]

    asyncio.run(_run())


# -- 键位拆分(收尾补丁:Esc 仅中断 / Ctrl+C 退出)-----------------------------


def test_escape_only_interrupts_not_quits():
    """Esc → interrupt 回调(不触发退出)。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        interrupts: list[str] = []
        quits: list[str] = []
        backend.on_interrupt(lambda: interrupts.append("i"))
        backend.on_quit(lambda: quits.append("q"))
        async with app.run_test(size=(80, 24)):
            app.action_interrupt()
            assert interrupts == ["i"] and quits == []

    asyncio.run(_run())


def test_ctrl_j_inserts_newline_fallback():
    """Ctrl+J 兜底换行:无 kitty 协议的终端 Shift+Enter 与 Enter 同码。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        async with app.run_test(size=(80, 24)) as pilot:
            app.composer.input.text = "第一行"
            app.composer.input.move_cursor(app.composer.input.document.end)
            await pilot.press("ctrl+j")
            await pilot.press(*list("第二行"))
            await pilot.pause()
            assert app.composer.input.text == "第一行\n第二行"
            assert app.composer.styles.height.value == 3 + 1  # 两行输入 + 分隔线

    asyncio.run(_run())


def test_soft_wrap_grows_composer_height():
    """(回归)单行超长输入软换行后按渲染行增高,而非固定一行高滚动视图。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        async with app.run_test(size=(100, 32)) as pilot:
            app.composer.input.text = "a" * 150  # 单逻辑行,软换行折成 2 渲染行
            await pilot.pause()
            assert app.composer.styles.height.value == 3 + 1
            app.composer.input.text = "short"
            await pilot.pause()
            assert app.composer.styles.height.value == 3

    asyncio.run(_run())


def test_ctrl_c_and_ctrl_q_quit():
    """Ctrl+C / Ctrl+Q → quit 回调;ctrl+c 覆盖 textual 系统 help_quit 绑定。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        quits: list[str] = []
        backend.on_quit(lambda: quits.append("q"))
        async with app.run_test(size=(80, 24)):
            app.action_quit()
            assert quits == ["q"]
            # 应用绑定优先级覆盖系统绑定:ctrl+c 指向 quit 而非 help_quit
            keymap = app._bindings.get_bindings_for_key("ctrl+c")
            assert any(b.action == "quit" for b in keymap)
            assert not any(b.action == "help_quit" for b in keymap)

    asyncio.run(_run())


# -- 终端背景融合(spec「终端背景融合」)----------------------------------------


def test_no_default_background_filter():
    """过滤器剥离 default 背景;显式色值背景与无样式 segment 原样透传。"""
    from rich.segment import Segment
    from rich.style import Style
    from textual.color import Color

    from codeagent.app.tui.textual_backend import _NoDefaultBackground, _strip_default_bg

    filt = _NoDefaultBackground()
    bg = Color(0, 0, 0)
    default_bg = Segment("a", Style(color="#ff0000", bgcolor="default"))
    explicit_bg = Segment("b", Style(color="#ff0000", bgcolor="#2b2b2b"))
    no_style = Segment("c", None)

    out = filt.apply([default_bg, explicit_bg, no_style], bg)
    assert out[0].style is not None
    assert out[0].style.bgcolor is None  # default 背景被剥离
    assert out[0].style.color == default_bg.style.color  # 前景等属性保留
    assert out[1] is explicit_bg  # 显式背景原样透传
    assert out[2] is no_style  # 无样式原样透传

    # _strip_default_bg 全字段重建:前景/字重等保留,仅背景移除。
    s = Style(color="#00ff00", bgcolor="default", bold=True, italic=True, underline=True)
    s2 = _strip_default_bg(s)
    assert s2.bgcolor is None
    assert s2.color == s.color and s2.bold and s2.italic and s2.underline


def test_on_mount_installs_background_blending():
    """on_mount:过滤器置于过滤链头部,四处背景改为终端默认背景语义。"""
    from textual.color import Color

    from codeagent.app.tui.textual_backend import TextualBackend, _NoDefaultBackground

    ansi_default = Color.parse("ansi_default")

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        async with app.run_test(size=(80, 24)):
            assert isinstance(app._filters[0], _NoDefaultBackground)
            assert app.styles.background == ansi_default
            assert app.screen.styles.background == ansi_default
            assert app.transcript.styles.background == ansi_default
            assert app.composer.input.styles.background == ansi_default

    asyncio.run(_run())


# -- 登录掩码输入(tui-login-command) ----------------------------------------


def test_input_mask_switches_composer_components():
    """(tui-login-command)set_input_mask:普通输入 ↔ 密码输入 display 互斥。"""
    from codeagent.app.tui.textual_backend import TextualBackend
    from textual.color import Color

    async def _run() -> None:
        backend = TextualBackend()
        composer = backend._app.composer
        async with backend._app.run_test(size=(80, 24)) as pilot:
            assert composer.input.display  # 初始为普通输入
            assert not composer.key_input.display
            assert not composer.login_label.display
            assert not composer.login_hint.display

            backend.set_input_mask(True)
            await pilot.pause()  # focus() 经消息循环排队生效
            assert not composer.input.display
            assert composer.key_input.display
            assert composer.login_label.display
            assert str(composer.login_label.content) == "KEY"
            assert composer.login_hint.display
            assert str(composer.login_hint.content) == "Enter 保存  ·  Esc 取消"
            assert composer.styles.height.value == 4
            assert composer.key_input.styles.background == Color.parse("#171a1d")
            assert composer.key_input.styles.border.top[1] == Color.parse("#171a1d")
            assert composer.top_rule.styles.color == Color.parse("#39d9ff")
            assert composer.bottom_rule.styles.color == Color.parse("#39d9ff")
            assert backend._app.focused is composer.key_input

            backend.set_input_mask(False)
            await pilot.pause()
            assert composer.input.display
            assert not composer.key_input.display
            assert not composer.login_label.display
            assert not composer.login_hint.display
            assert composer.styles.height.value == 3
            assert composer.top_rule.styles.color == Color.parse("#5a5a5a")
            assert composer.bottom_rule.styles.color == Color.parse("#5a5a5a")
            assert backend._app.focused is composer.input
            # 退出掩码:普通输入提示还原,密码输入内容清空
            assert composer.input.placeholder == "输入消息..."

    asyncio.run(_run())


def test_key_input_submits_plaintext_and_clears():
    """(tui-login-command)掩码提交:通知原文(非掩码字符),提交后清空。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        submits: list[str] = []
        backend.on_submit(submits.append)
        async with backend._app.run_test(size=(80, 24)) as pilot:
            backend.set_input_mask(True)
            backend.set_input_placeholder("输入 DEEPSEEK_API_KEY")
            assert backend._app.composer.key_input.placeholder == "输入 DEEPSEEK_API_KEY"

            key_input = backend._app.composer.key_input
            key_input.value = "sk-secret-123"
            key_input.action_submit()
            await pilot.pause()  # post_message 异步分发
            assert submits == ["sk-secret-123"]  # 提交的是原文
            assert key_input.value == ""  # 提交后清空

    asyncio.run(_run())


def test_key_input_does_not_consume_escape():
    """(tui-login-command)Esc 不绑定在密码输入上:冒泡到应用层由视图取消。"""
    from codeagent.app.tui.textual_backend import _KeyInput

    assert "escape" not in [b.key for b in _KeyInput.BINDINGS]


def test_key_input_empty_submit_ignored():
    """(tui-login-command)空白提交不触发通知(空值由视图层提示)。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        submits: list[str] = []
        backend.on_submit(submits.append)
        async with backend._app.run_test(size=(80, 24)):
            key_input = backend._app.composer.key_input
            key_input.value = "   "
            key_input.action_submit()
            assert submits == []

    asyncio.run(_run())
