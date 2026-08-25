"""Tests for the split session-store module boundaries."""

from codeagent.session import session as session_module
from codeagent.session import store as store_module
from codeagent.core.messages import Message
from codeagent.session.memory_store import MemoryStore
from codeagent.session.session_persistence import SessionPersistence
from codeagent.session.session_runtime import SessionRuntime
from codeagent.session.store import UsageStats


def test_store_facade_preserves_public_symbols() -> None:
    from codeagent.session.json_file_store import JsonFileStore
    from codeagent.session.memory_store import MemoryStore
    from codeagent.session.store_codec import (
        _dict_to_message,
        _message_to_dict,
    )
    from codeagent.session.store_models import (
        CompactionEntry,
        CompactionState,
        SessionRef,
        SessionStore,
        UsageStats,
    )

    assert store_module.JsonFileStore is JsonFileStore
    assert store_module.MemoryStore is MemoryStore
    assert store_module.CompactionEntry is CompactionEntry
    assert store_module.CompactionState is CompactionState
    assert store_module.SessionRef is SessionRef
    assert store_module.SessionStore is SessionStore
    assert store_module.UsageStats is UsageStats
    assert callable(_dict_to_message)
    assert callable(_message_to_dict)


def test_session_facade_keeps_public_constants() -> None:
    assert session_module.AgentSession.__name__ == "AgentSession"
    assert session_module.DEFAULT_CONTEXT_WINDOW > 0


def test_session_runtime_owns_run_control_state() -> None:
    runtime = SessionRuntime(lambda event: None)

    run_id = runtime.start_run()
    runtime.inject("follow-up")
    runtime.respond_approval("request-1", True)

    assert runtime.active_run_id == run_id
    assert runtime.inject_queue.get_nowait() == "follow-up"
    assert runtime.confirm_queue.get_nowait() == ("request-1", True)


def test_session_persistence_defers_creation_until_commit() -> None:
    store = MemoryStore()
    persistence = SessionPersistence(
        store,
        "pending",
        defer_persistence=True,
        persistence_options={"model": "fake"},
    )

    restored = persistence.load()
    assert restored.history == []
    assert not persistence.persisted
    assert store.get("pending") is None

    persistence.commit_turn(
        [Message(role="user", content="hello")],
        UsageStats(input_tokens=3),
        context_tokens=3,
    )

    assert persistence.persisted
    assert store.get("pending") is not None
    assert store.load_messages("pending")[0].content == "hello"
    assert store.get_meta("pending", "last_context_tokens") == 3
