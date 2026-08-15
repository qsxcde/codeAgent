"""tests/tui/test_textual_backend.py:textual 后端渲染通道的离线断言。

textual 延迟 import(与 src 侧一致)。覆盖 fix-tui-command-completion D3:
建议条高度计入 composer,输入行不被裁剪;T-47 滚动:滚轮转发与
PageUp/PageDown 按键焦点分派。
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


def test_page_keys_dispatch_by_focus():
    """PageUp/PageDown:输入框聚焦归编辑区(不滚动视口),否则滚动一页(spec「键盘滚动」)。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        scrolls: list[int] = []
        backend.on_scroll(scrolls.append)
        async with app.run_test(size=(80, 24)):
            page = max(1, app.transcript.size.height - 1)
            # 直接置 has_focus 标志测分派逻辑(textual 的 focus/blur 消息泵是引擎职责,
            # 不在本测试范围;分支读取的就是该标志)。
            app.composer.input.has_focus = True
            app.action_page_up()
            app.action_page_down()
            assert scrolls == []  # 输入框聚焦:按键归属编辑区
            app.composer.input.has_focus = False
            app.action_page_up()
            app.action_page_down()
            assert scrolls == [page, -page]

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


def test_confirmation_keys_dispatch_by_active_state():
    """确认激活时 y/n → 响应回调;未激活时 y/n 正常输入文本。"""
    from codeagent.app.tui.textual_backend import TextualBackend

    async def _run() -> None:
        backend = TextualBackend()
        app = backend._app
        responses: list[bool] = []
        backend.on_confirmation_response(responses.append)
        async with app.run_test(size=(80, 24)):
            # 未激活:y/n 落入输入文本
            app.composer.input.action_confirm_yes()
            app.composer.input.action_confirm_no()
            assert responses == []
            assert app.composer.input.text == "yn"
            # 激活:y/n 转为响应,不落入文本
            app.composer.input.text = ""
            backend.confirmation_active = True
            app.composer.input.action_confirm_yes()
            app.composer.input.action_confirm_no()
            assert responses == [True, False]
            assert app.composer.input.text == ""

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
