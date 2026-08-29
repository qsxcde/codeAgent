"""Archive and deletion behavior shared by session stores."""

from __future__ import annotations

import json
import os

import pytest

from codeagent.core.contracts.messages import Message
from codeagent.session.persistence import JsonFileStore, MemoryStore, SessionQuery


@pytest.fixture(params=("jsonl", "memory"), ids=("jsonl", "memory"))
def store(request, tmp_path):
    if request.param == "jsonl":
        return JsonFileStore(tmp_path / "sessions")
    return MemoryStore()


def test_archive_is_reversible_and_default_query_hides_it(store):
    store.create("s1", model="fake-model")
    message = Message(role="user", content="preserve this history")
    store.append_message("s1", message)
    before_messages = store.load_messages("s1")
    before_activity = store.get("s1").last_activity_at

    store.archive("s1")

    assert store.get("s1").archived is True
    assert store.list() == []
    assert [ref.id for ref in store.list(SessionQuery(archived=True))] == ["s1"]
    assert [ref.id for ref in store.list(SessionQuery(archived=None))] == ["s1"]
    assert store.load_messages("s1") == before_messages
    assert store.get("s1").last_activity_at == before_activity

    store.archive("s1", archived=False)
    assert store.get("s1").archived is False
    assert [ref.id for ref in store.list()] == ["s1"]


def test_old_index_rebuild_defaults_archive_to_false(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    index_path = tmp_path / "sessions" / "s1.index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["session"].pop("archived")
    index_path.write_text(json.dumps(index) + "\n", encoding="utf-8")

    assert store.get("s1").archived is False
    rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
    assert rebuilt["session"]["archived"] is False


def test_delete_removes_only_target_jsonl_and_index(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    store.create("s2")
    store.delete("s1")

    assert store.get("s1") is None
    assert not (tmp_path / "sessions" / "s1.jsonl").exists()
    assert not (tmp_path / "sessions" / "s1.index.json").exists()
    assert store.get("s2") is not None
    assert (tmp_path / "sessions" / "s2.jsonl").exists()


def test_delete_rejects_path_traversal_and_symlink_target(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    with pytest.raises(ValueError, match="会话 id"):
        store.delete("../s1")

    if os.name == "nt":
        pytest.skip("Windows CI may not permit symlink creation")
    outside = tmp_path / "outside.jsonl"
    outside.write_text("must stay\n", encoding="utf-8")
    os.symlink(outside, tmp_path / "sessions" / "linked.jsonl")
    with pytest.raises(ValueError, match="符号链接"):
        store.delete("linked")
    assert outside.read_text(encoding="utf-8") == "must stay\n"
