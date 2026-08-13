"""app/tui/main.py:TUI 入口——装配经组合根,只启动。

`app/main.py --tui` 转交此处;headless 保持默认。装配(含 footer 的
model/effort 解析)全部在组合根 ``container.create_tui_app`` 完成,本文件
不跨层 import(design D5)。
"""

from __future__ import annotations

__all__ = ["run_tui"]


def run_tui() -> None:
    """启动交互式终端(alt 屏,阻塞直到退出)。"""
    from codeagent.app import container

    container.create_tui_app().start()
