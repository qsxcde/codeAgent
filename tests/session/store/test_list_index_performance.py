"""会话列表索引命中和失效隔离契约测试。"""

from __future__ import annotations

import json

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import AgentLoopConfig
from codeagent.core.contracts.messages import Message
from codeagent.session import SessionManager
from codeagent.session.persistence import JsonFileStore, SessionQuery
from codeagent.session.persistence.jsonl import store as jsonl_store


def _indexed_store(tmp_path, count: int = 8) -> JsonFileStore:
    store = JsonFileStore(tmp_path / "sessions")
    for index in range(count):
        session_id = f"s{index:02d}"
        store.create(session_id, model="model-a")
        store.append_message(session_id, Message(role="user", content=f"topic-{index}"))
    return store


def test_many_session_queries_use_valid_indexes_without_source_scans(tmp_path, monkeypatch):
    store = _indexed_store(tmp_path)

    def fail_rebuild(*args, **kwargs):
        raise AssertionError("有效索引命中时不应扫描 JSONL")

    monkeypatch.setattr(store, "_build_index", fail_rebuild)

    assert len(store.list()) == 8
    assert [ref.id for ref in store.list(SessionQuery(text="topic", model="model-a"))] == [
        f"s{index:02d}" for index in range(8)
    ]


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "stale"])
def test_one_invalid_index_rebuilds_only_its_session(tmp_path, monkeypatch, mutation):
    store = _indexed_store(tmp_path, count=3)
    index_path = tmp_path / "sessions" / "s01.index.json"
    source_path = tmp_path / "sessions" / "s01.jsonl"
    if mutation == "missing":
        index_path.unlink()
    elif mutation == "corrupt":
        index_path.write_text("not-json\n", encoding="utf-8")
    else:
        with source_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "usage", "input": 1}) + "\n")

    rebuilt: list[str] = []
    original_build = store._build_index

    def observe_rebuild(path):
        rebuilt.append(path.stem)
        return original_build(path)

    monkeypatch.setattr(store, "_build_index", observe_rebuild)

    assert [ref.id for ref in store.list()] == ["s00", "s01", "s02"]
    assert rebuilt == ["s01"]


def test_failed_source_rebuild_does_not_block_other_sessions(tmp_path):
    store = _indexed_store(tmp_path, count=3)
    bad_path = tmp_path / "sessions" / "s01.jsonl"
    bad_path.write_text("not-json\n", encoding="utf-8")

    assert [ref.id for ref in store.list()] == ["s00", "s02"]


def test_continue_recent_uses_index_candidates_and_restores_only_selected_session(
    tmp_path, monkeypatch
):
    timestamps = iter(
        (
            "2026-08-30T00:00:00.000Z",
            "2026-08-30T00:00:01.000Z",
            "2026-08-30T00:00:02.000Z",
            "2026-08-30T00:00:03.000Z",
        )
    )
    monkeypatch.setattr(jsonl_store, "_now", lambda: next(timestamps))
    store = JsonFileStore(tmp_path / "sessions")
    store.create("older")
    store.append_message("older", Message(role="user", content="older"))
    store.create("newer")
    store.append_message("newer", Message(role="user", content="newer"))

    def fail_rebuild(*args, **kwargs):
        raise AssertionError("最近会话候选选择不应重建有效索引")

    monkeypatch.setattr(store, "_build_index", fail_rebuild)
    scanned: list[str] = []
    original_iter = store._iter_entries

    def observe_scan(path):
        scanned.append(path.stem)
        yield from original_iter(path)

    monkeypatch.setattr(store, "_iter_entries", observe_scan)
    recovered: list[str] = []
    original_report = store.recovery_report

    def observe_report(session_id):
        recovered.append(session_id)
        return original_report(session_id)

    monkeypatch.setattr(store, "recovery_report", observe_report)
    manager = SessionManager(
        AgentLoopConfig(model=ChatModelPort(FakeClient(response="unused")), tools=[]),
        store=store,
    )

    session = manager.continue_recent()

    assert session.session_id == "newer"
    assert recovered == ["newer"]
    assert set(scanned) == {"newer"}
