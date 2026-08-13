"""app/tui:交互式终端形态(MVP)。

组件纯渲染 + TuiBackend 端口 + textual 实现(design D1/D2);消费 AgentSession
事件流驱动组件渲染。
"""

__all__ = ["run_tui"]


def run_tui() -> None:
    from codeagent.app.tui.main import run_tui as _run_tui

    _run_tui()
