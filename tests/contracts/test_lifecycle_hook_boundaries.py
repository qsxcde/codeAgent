from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.mark.contract
def test_core_lifecycle_hook_contract_has_no_concrete_layer_imports() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "codeagent"
        / "core"
        / "contracts"
        / "hooks.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.append(node.module)

    forbidden = ("codeagent.ai", "codeagent.tools", "codeagent.session", "codeagent.app")
    assert not [module for module in imported if module.startswith(forbidden)]
