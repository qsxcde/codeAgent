"""TUI 分层护栏：纯渲染层不能反向依赖协调器或具体引擎。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


TUI_ROOT = Path(__file__).resolve().parents[2] / "src" / "codeagent" / "app" / "tui"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    ("module", "forbidden"),
    (
        (
            "primitives.py",
            {
                "codeagent.app.tui.blocks",
                "codeagent.app.tui.transcript",
                "codeagent.app.tui.status",
                "codeagent.app.tui.model",
                "codeagent.app.tui.view",
                "textual",
            },
        ),
        (
            "blocks.py",
            {
                "codeagent.app.tui.transcript",
                "codeagent.app.tui.status",
                "codeagent.app.tui.model",
                "codeagent.app.tui.view",
                "textual",
            },
        ),
        (
            "transcript.py",
            {
                "codeagent.app.tui.status",
                "codeagent.app.tui.model",
                "codeagent.app.tui.view",
                "textual",
            },
        ),
        (
            "status.py",
            {
                "codeagent.app.tui.blocks",
                "codeagent.app.tui.transcript",
                "codeagent.app.tui.model",
                "codeagent.app.tui.view",
                "textual",
            },
        ),
        (
            "model.py",
            {"codeagent.app.tui.view", "textual"},
        ),
    ),
)
def test_tui_layer_dependencies_are_one_way(
    module: str, forbidden: set[str]
) -> None:
    """每个拆分后的层只能向基础层或运行时协议方向依赖。"""
    path = TUI_ROOT / module
    assert path.exists(), f"拆分模块缺失: {path}"
    imported = _imports(path)
    violations = [
        name
        for name in imported
        for banned in forbidden
        if name == banned or name.startswith(banned + ".")
    ]
    assert not violations, f"{module} 反向依赖: {violations}"


def test_markdown_and_backend_use_primitives_layer() -> None:
    """Markdown 与后端共享基础值对象，不再从组件总入口取类型。"""
    assert "codeagent.app.tui.primitives" in _imports(TUI_ROOT / "md_renderer.py")
    assert "codeagent.app.tui.primitives" in _imports(TUI_ROOT / "backend.py")
    assert "codeagent.app.tui.primitives" in _imports(TUI_ROOT / "textual_backend.py")


def test_view_is_lifecycle_facade() -> None:
    """view 只保留装配/生命周期桥接，协调职责不回流到 TuiApp。"""
    source = (TUI_ROOT / "view.py").read_text(encoding="utf-8")
    for method in (
        "_cmd_help",
        "_suggestion_context",
        "_run_conversation",
        "_cmd_sessions",
        "_hydrate_current_session",
        "_on_task_event",
    ):
        assert f"def {method}" not in source
    assert "TuiCommandCoordinator" in source
    assert "TuiSessionCoordinator" in source
    assert "TuiConversationCoordinator" in source
