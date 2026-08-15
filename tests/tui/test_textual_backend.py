"""tests/tui/test_textual_backend.py:textual 后端渲染通道的离线断言。

textual 延迟 import(与 src 侧一致)。覆盖 fix-tui-command-completion D3:
建议条高度计入 composer,输入行不被裁剪。
"""

import asyncio


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
