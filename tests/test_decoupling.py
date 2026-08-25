"""tests/test_decoupling.py:分层依赖规则强制校验(架构判据自动化,重写 T-27)。

判据(v0.1 重构后按 `app/` 新分层重写):
- 跨层 import 只允许出现在 `app/container.py`、`app/composition/` / `app/main.py`(组合根与入口);
- `core/` 不 import config/tools/ai/session(横切解耦判据);
- `session/` 不 import ai/tools/config(纵切解耦判据);
- `ai/`、`tools/` 不反向依赖 core/session;
- `app/tui/` 不 import ai/tools/config;具体引擎(textual)只允许出现在
  `textual_backend.py`(TuiBackend 端口解耦)。

实现:AST 解析 import 语句(注释/docstring 中的字面量不参与判定),
按文件所在层匹配禁止前缀。测试代码可跨层 import,不在扫描范围。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "codeagent"

#: 例外文件/目录:跨层 import 全允许(组合根与入口)。
_COMPOSITION_ROOTS = {"app/container.py", "app/main.py"}
#: 具体引擎唯一允许出现的文件(端口适配器解耦)。
_ENGINE_FILE = "app/tui/textual_backend.py"


def _rel(path: Path) -> str:
    return path.relative_to(SRC_ROOT).as_posix()


def _forbidden_for(rel: str) -> list[str]:
    """返回该文件禁止 import 的模块前缀;空列表 = 无限制。"""
    if rel in _COMPOSITION_ROOTS:
        return []
    if rel.startswith("app/composition/"):
        return []
    if rel.startswith("core/"):
        return ["codeagent.config", "codeagent.tools", "codeagent.ai", "codeagent.session"]
    if rel.startswith("session/"):
        return ["codeagent.ai", "codeagent.tools", "codeagent.config"]
    if rel.startswith("ai/"):
        return ["codeagent.core", "codeagent.session"]
    if rel.startswith("tools/"):
        return ["codeagent.core", "codeagent.session", "codeagent.ai", "codeagent.app"]
    if rel.startswith("app/tui/"):
        forbidden = ["codeagent.ai", "codeagent.tools", "codeagent.config"]
        if rel != _ENGINE_FILE:
            forbidden.append("textual")
        return forbidden
    if rel.startswith("app/"):
        return ["codeagent.core", "codeagent.session", "codeagent.ai", "codeagent.tools"]
    return []  # 顶层 __init__ / resources(占位,无依赖)


def _imported_modules(tree: ast.Module) -> list[str]:
    """文件内 import 的绝对模块名;相对导入(level>0)为包内引用,不跨层,跳过。"""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.append(node.module)
    return modules


PY_FILES = sorted(p for p in SRC_ROOT.rglob("*.py") if "__pycache__" not in str(p))


@pytest.mark.parametrize("path", PY_FILES, ids=_rel)
def test_layer_import_rules(path: Path) -> None:
    """每层只允许按依赖方向 import(跨层 import 仅组合根/入口)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = _forbidden_for(_rel(path))
    violations: list[str] = []
    for module in _imported_modules(tree):
        for banned in forbidden:
            if module == banned or module.startswith(banned + "."):
                violations.append(f"import {module}(禁止 {banned})")
    assert not violations, f"{_rel(path)} 违反分层依赖: {violations}"


def test_composition_roots_exist() -> None:
    """组合根与入口存在(例外文件缺失会让跨层 import 规则形同虚设)。"""
    for rel in _COMPOSITION_ROOTS:
        assert (SRC_ROOT / rel).exists(), f"{rel} 缺失"


def test_scan_has_content() -> None:
    """扫描覆盖全部源码文件(防空转:规则写错导致零文件被测)。"""
    rels = [_rel(p) for p in PY_FILES]
    assert len(PY_FILES) >= 60
    assert any(r.startswith("core/") for r in rels)
    assert any(r.startswith("session/") for r in rels)
    assert any(r.startswith("ai/") for r in rels)
    assert any(r.startswith("tools/") for r in rels)
    assert any(r.startswith("app/tui/") for r in rels)


def test_textual_only_in_engine_backend() -> None:
    """具体引擎 textual 只允许出现在 textual_backend.py(端口适配器解耦)。"""
    for path in PY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        has_textual = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name.startswith("textual") for alias in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.startswith("textual")
            )
            for node in ast.walk(tree)
        )
        if has_textual:
            assert _rel(path) == _ENGINE_FILE, f"textual 出现在非引擎文件 {_rel(path)}"


def test_composition_modules_do_not_import_container_facade() -> None:
    """组合实现只能被 façade 导出,不能反向导入 façade 形成循环依赖。"""
    composition_root = SRC_ROOT / "app" / "composition"
    for path in sorted(composition_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = _imported_modules(tree)
        assert "codeagent.app.container" not in imported, _rel(path)
