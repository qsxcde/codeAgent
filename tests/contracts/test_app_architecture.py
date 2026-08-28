"""应用层模块图和资源所有权契约。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2] / "src" / "codeagent" / "app"


def _module_name(path: Path) -> str:
    relative = path.relative_to(APP_ROOT).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return "codeagent.app" + ("." + ".".join(parts) if parts else "")


def _imports(path: Path, modules: set[str]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    current = _module_name(path).split(".")
    package = current[:-1] if path.name != "__init__.py" else current
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names if alias.name in modules)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module in modules:
                    imported.add(node.module)
                continue
            base = package[: len(package) - node.level + 1]
            prefix = ".".join(base)
            if node.module:
                target = f"{prefix}.{node.module}"
                if target in modules:
                    imported.add(target)
            else:
                for alias in node.names:
                    target = f"{prefix}.{alias.name}"
                    if target in modules:
                        imported.add(target)
    return imported


@pytest.mark.contract
def test_app_import_graph_is_acyclic() -> None:
    paths = sorted(APP_ROOT.rglob("*.py"))
    modules = {_module_name(path) for path in paths}
    graph = {module: _imports(path, modules) for path, module in ((path, _module_name(path)) for path in paths)}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in visiting:
            raise AssertionError(f"应用层存在循环依赖: {module}")
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)


@pytest.mark.contract
def test_runtime_ownership_is_not_a_global_mutable_registry() -> None:
    path = APP_ROOT / "composition" / "runtime" / "factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            target.id == "_RUNTIMES_BY_CONFIG"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        )
    ]
    assert not any(
        isinstance(node.value, (ast.Dict, ast.List, ast.Set))
        for node in assignments
    )
    source = path.read_text(encoding="utf-8")
    assert "_runtime_owner" in source
