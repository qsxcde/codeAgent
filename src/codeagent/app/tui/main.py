"""app/tui/main.py:TUI 入口——装配经组合根,只启动。

`app/main.py --tui` 转交此处;headless 保持默认。装配(含 footer 的
model/effort 解析)全部在组合根 ``container.create_tui_app`` 完成,本文件
不跨层 import(design D5)。
"""

from __future__ import annotations

__all__ = ["run_tui"]


def run_tui() -> None:
    """启动交互式终端(alt 屏,阻塞直到退出)。

    会话存储装配在入口处完成(与 headless ``--continue/--session`` 同源):
    TUI 会话持久化到 ``~/.codeagent/sessions/``——``/sessions`` 切换、
    ``/fork`` 分叉、``/compact`` 压缩与用量落库(/status 展示)全部依赖 store;
    不装配则 TUI 会话不落盘、用量无落库点(回归:cost-transparency 真实测试
    /status 显示「用量: (无)」)。
    """
    from codeagent.app import container
    from codeagent.app.config import CONFIG_DIR
    from codeagent.session.persistence.jsonl_store import JsonFileStore

    container.create_tui_app(store=JsonFileStore(CONFIG_DIR / "sessions")).start()
