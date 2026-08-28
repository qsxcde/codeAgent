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
            "presentation/primitives.py",
            {
                "codeagent.app.tui.presentation.blocks",
                "codeagent.app.tui.state.transcript",
                "codeagent.app.tui.presentation.status",
                "codeagent.app.tui.state.model",
                "codeagent.app.tui.application",
                "textual",
            },
        ),
        (
            "presentation/blocks/__init__.py",
            {
                "codeagent.app.tui.state.transcript",
                "codeagent.app.tui.presentation.status",
                "codeagent.app.tui.state.model",
                "codeagent.app.tui.application",
                "textual",
            },
        ),
        (
            "state/transcript.py",
            {
                "codeagent.app.tui.presentation.status",
                "codeagent.app.tui.state.model",
                "codeagent.app.tui.application",
                "textual",
            },
        ),
        (
            "presentation/status.py",
            {
                "codeagent.app.tui.presentation.blocks",
                "codeagent.app.tui.state.transcript",
                "codeagent.app.tui.state.model",
                "codeagent.app.tui.application",
                "textual",
            },
        ),
        (
            "state/model.py",
            {"codeagent.app.tui.application", "textual"},
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
    assert "from .primitives import" in (TUI_ROOT / "presentation" / "md_renderer.py").read_text(encoding="utf-8")
    assert "from ..presentation.primitives import" in (TUI_ROOT / "ports" / "backend.py").read_text(encoding="utf-8")
    assert "from ...presentation.primitives import" in (TUI_ROOT / "adapters" / "textual" / "backend.py").read_text(encoding="utf-8")


def test_application_is_the_tui_lifecycle_root() -> None:
    """应用壳位于规范 application 模块，旧 view 入口已删除。"""
    source = (TUI_ROOT / "application.py").read_text(encoding="utf-8")
    assert "class TuiApp" in source
    assert not (TUI_ROOT / "view.py").exists()
