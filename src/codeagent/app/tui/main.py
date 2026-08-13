"""app/tui/main.py:TUI 入口——装配 AgentSession + TuiApp + textual 后端。

`app/main.py --tui` 转交此处;headless 保持默认。
"""

from __future__ import annotations

__all__ = ["run_tui"]


def run_tui() -> None:
    """启动交互式终端(alt 屏,阻塞直到退出)。"""
    from codeagent.app import container
    from codeagent.app.tui.textual_backend import TextualBackend
    from codeagent.app.tui.view import TuiApp

    session = container.create_agent_session()
    app = TuiApp(session, TextualBackend())
    app.start()
