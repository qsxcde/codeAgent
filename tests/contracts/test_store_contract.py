"""Store backends share the same public session contract."""

from __future__ import annotations

import pytest

from codeagent.core.contracts.messages import Message
from codeagent.session.persistence.jsonl import JsonFileStore
from codeagent.session.persistence.memory_store import MemoryStore


@pytest.fixture(params=("jsonl", "memory"), ids=("jsonl", "memory"))
def store(request, tmp_path):
    if request.param == "jsonl":
        return JsonFileStore(tmp_path / "sessions")
    return MemoryStore()


def test_store_crud_meta_and_usage_contract(store):
    ref = store.create("s1", cwd="/workspace", model="fake-model", effort="high")
    user = Message(role="user", content="hello")
    assistant = Message(role="assistant", content="world", parent_id=user.id)
    store.append_message("s1", user)
    store.append_message("s1", assistant)
    store.set_meta("s1", "title", "Contract")
    store.append_usage("s1", {"input_tokens": 3, "output_tokens": 2})

    loaded_ref = store.get("s1")
    assert loaded_ref is not None
    assert loaded_ref.id == ref.id
    assert loaded_ref.cwd == ref.cwd
    assert loaded_ref.model == ref.model
    assert loaded_ref.effort == ref.effort
    assert loaded_ref.title == "hello"
    assert [message.content for message in store.load_messages("s1")] == ["hello", "world"]
    assert store.get_meta("s1", "title") == "Contract"
    assert store.load_usage("s1").input_tokens == 3
    assert store.load_usage("s1").output_tokens == 2


def test_store_activity_timestamp_contract(store, monkeypatch):
    """创建和成功追加消息都会更新最近活动时间。"""
    clock = iter(
        (
            "2026-08-27T00:00:00.000",
            "2026-08-27T00:00:01.000",
        )
    )
    module = (
        "codeagent.session.persistence.jsonl.store"
        if isinstance(store, JsonFileStore)
        else "codeagent.session.persistence.memory_store"
    )
    monkeypatch.setattr(module + "._now", lambda: next(clock))

    created = store.create("s1")
    store.append_message("s1", Message(role="user", content="hello"))

    updated = store.get("s1")
    assert updated is not None
    assert created.last_activity_at == created.timestamp
    assert updated.last_activity_at == "2026-08-27T00:00:01.000"


def test_store_recent_activity_sort_contract(store, monkeypatch):
    """recent 依据最后活动时间，而不是会话创建时间。"""
    clock = iter(
        (
            "2026-08-27T00:00:00.000",
            "2026-08-27T00:00:01.000",
            "2026-08-27T00:00:02.000",
        )
    )
    module = (
        "codeagent.session.persistence.jsonl.store"
        if isinstance(store, JsonFileStore)
        else "codeagent.session.persistence.memory_store"
    )
    monkeypatch.setattr(module + "._now", lambda: next(clock))

    store.create("first")
    store.create("second")
    store.append_message("first", Message(role="user", content="reopened"))

    assert [ref.id for ref in store.list()] == ["second", "first"]


def test_store_fork_contract_copies_history_before_target(store):
    store.create("source")
    first = Message(role="user", content="first")
    reply = Message(role="assistant", content="reply", parent_id=first.id)
    target = Message(role="user", content="target", parent_id=reply.id)
    for message in (first, reply, target):
        store.append_message("source", message)

    fork = store.fork("source", target.id, "branch")

    assert fork.parent_session == "source"
    assert [message.content for message in store.load_messages("branch")] == [
        "first",
        "reply",
    ]


def test_store_missing_session_is_consistent(store):
    assert store.get("missing") is None
    with pytest.raises(ValueError):
        store.load_messages("missing")
