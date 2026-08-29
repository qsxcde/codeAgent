"""Contract tests for the nested session responsibility packages."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


SESSION_ROOT = Path(__file__).resolve().parents[2] / "src" / "codeagent" / "session"


def test_manager_and_jsonl_are_real_responsibility_packages() -> None:
    manager_module = importlib.import_module("codeagent.session.manager")
    jsonl_module = importlib.import_module("codeagent.session.persistence.jsonl")
    persistence_module = importlib.import_module("codeagent.session.persistence")

    assert hasattr(manager_module, "SessionManager")
    assert hasattr(jsonl_module, "JsonFileStore")
    assert persistence_module.JsonFileStore is jsonl_module.JsonFileStore
    assert (SESSION_ROOT / "manager").is_dir()
    assert (SESSION_ROOT / "persistence" / "jsonl").is_dir()


def test_flat_jsonl_modules_are_removed() -> None:
    for module_name in (
        "codeagent.session.persistence.jsonl_store",
        "codeagent.session.persistence.jsonl_reading",
        "codeagent.session.persistence.jsonl_writing",
        "codeagent.session.persistence.jsonl_indexing",
        "codeagent.session.persistence.jsonl_forking",
    ):
        assert importlib.util.find_spec(module_name) is None
