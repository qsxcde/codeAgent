"""Contract tests for the session execution/finalization boundary."""

from __future__ import annotations

import asyncio
import threading

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import Agent, AgentContext, AgentLoopConfig, EventType, Message
from codeagent.session import AgentSession, EventBus
from codeagent.session.persistence.jsonl_store import JsonFileStore
from codeagent.session.persistence.memory_store import MemoryStore
from codeagent.session.persistence.models import UsageStats
from codeagent.session.runtime.state import CommitStatus, RunPhase
from tests.session.behavior.fixtures import _compact_session, _long, _session


class _FailingUsageMemoryStore(MemoryStore):
    def append_usage(self, session_id, usage):
        raise OSError("usage write failed")


class _FailingUsageJsonStore(JsonFileStore):
    def append_usage(self, session_id, usage):
        raise OSError("usage write failed")


def test_json_commit_failure_does_not_restore_over_a_concurrent_append(tmp_path, monkeypatch):
    """Rollback truncates only its own append batch under the path lock."""
    store = _FailingUsageJsonStore(tmp_path / "sessions")
    store.create("concurrent")
    batch_started = threading.Event()
    append_started = threading.Event()
    original_append_message = store.append_message

    def observe_batch(session_id, message):
        batch_started.set()
        assert append_started.wait(1)
        return original_append_message(session_id, message)

    monkeypatch.setattr(store, "append_message", observe_batch)
    error: list[BaseException] = []

    def commit() -> None:
        try:
            store.commit_turn(
                "concurrent",
                [Message(role="user", content="turn")],
                UsageStats(input_tokens=1),
                context_tokens=1,
            )
        except BaseException as exc:  # noqa: BLE001 - assert rollback path
            error.append(exc)

    worker = threading.Thread(target=commit)
    worker.start()
    append_done = threading.Event()
    append_error: list[BaseException] = []

    def append_other() -> None:
        append_started.set()
        try:
            store.append_message("concurrent", Message(role="user", content="other"))
        except BaseException as exc:  # noqa: BLE001 - assert worker completion
            append_error.append(exc)
        finally:
            append_done.set()

    append_worker = threading.Thread(target=append_other)
    assert batch_started.wait(1)
    append_worker.start()
    assert append_started.wait(1)
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert append_done.wait(5)
    append_worker.join(timeout=1)
    assert not append_worker.is_alive()

    assert error and isinstance(error[0], OSError)
    assert not append_error
    assert [message.content for message in store.load_messages("concurrent")] == [
        "other"
    ]


@pytest.mark.parametrize("store_kind", ("memory", "jsonl"))
async def test_persistence_failure_rolls_back_messages_and_usage(tmp_path, store_kind):
    """A failed message/usage batch is invisible in both store backends."""
    if store_kind == "memory":
        store = _FailingUsageMemoryStore()
    else:
        store = _FailingUsageJsonStore(tmp_path / "sessions")

    session = _session(
        FakeClient(
            response="reply",
            usage={"input_tokens": 7, "output_tokens": 2},
        ),
        store=store,
        session_id="failed-turn",
    )
    # Avoid making the failure test depend on deferred-header cleanup.
    if store.get(session.session_id) is None:
        store.create(session.session_id)
        session = _session(
            FakeClient(
                response="reply",
                usage={"input_tokens": 7, "output_tokens": 2},
            ),
            store=store,
            session_id="failed-turn",
        )

    seen: list = []
    session.subscribe(seen.append)
    await session.run("hello")

    assert session.history == []
    assert store.load_messages(session.session_id) == []
    assert store.load_usage(session.session_id).input_tokens == 0
    assert session.last_outcome is not None
    assert session.last_outcome.phase is RunPhase.FAILED
    assert session.last_outcome.commit_status is CommitStatus.PERSISTENCE_FAILED
    assert next(event for event in seen if event.type == EventType.ERROR).metadata[
        "error_code"
    ] == "persistence_error"


class _FailingSummarizer:
    async def summarize(self, messages, prev_summary):
        raise RuntimeError("summary failed")


class _SlowSummarizer:
    def __init__(self):
        self.started = asyncio.Event()

    async def summarize(self, messages, prev_summary):
        self.started.set()
        await asyncio.Event().wait()


async def test_compaction_failure_keeps_committed_turn_and_does_not_duplicate_usage():
    store = MemoryStore()
    model = FakeClient(
        response="reply",
        usage={"input_tokens": 5, "output_tokens": 1},
    )
    session = _compact_session(model, store=store, summarizer=None)
    for prompt in (_long("q1"), _long("q2"), _long("q3")):
        await session.run(prompt)
    before_usage = store.load_usage(session.session_id)
    session._summarizer = _FailingSummarizer()
    session._should_auto_compact = lambda: True
    seen: list = []
    session.subscribe(seen.append)

    await session.run(_long("q4"))

    assert any(message.content.startswith("q4") for message in session.history)
    assert len(store.load_messages(session.session_id)) == len(session.history)
    after_usage = store.load_usage(session.session_id)
    assert after_usage.input_tokens == before_usage.input_tokens + 5
    assert after_usage.output_tokens == before_usage.output_tokens + 1
    assert session.last_outcome is not None
    assert session.last_outcome.commit_status is CommitStatus.COMPACTION_FAILED
    assert session.last_outcome.phase is RunPhase.FAILED
    assert any(
        event.type == EventType.ERROR
        and event.metadata.get("error_code") == "compaction_failed"
        for event in seen
    )


async def test_cancellation_during_post_commit_compaction_preserves_turn():
    store = MemoryStore()
    model = FakeClient(
        response="reply", usage={"input_tokens": 5, "output_tokens": 1}
    )
    session = _compact_session(
        model,
        store=store,
        summarizer=None,
    )
    for prompt in (_long("q1"), _long("q2"), _long("q3")):
        await session.run(prompt)
    summarizer = _SlowSummarizer()
    session._summarizer = summarizer
    session._should_auto_compact = lambda: True

    task = asyncio.create_task(session.run(_long("q4")))
    await asyncio.wait_for(summarizer.started.wait(), timeout=1)
    session.steer("stale during finalization")
    session.abort()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert any(message.content.startswith("q4") for message in session.history)
    assert len(store.load_messages(session.session_id)) == len(session.history)
    assert session.last_outcome is not None
    assert session.last_outcome.phase is RunPhase.CANCELLED
    assert session.last_outcome.commit_status is CommitStatus.COMMITTED

    model.steps = [
        {
            "content": "",
            "tool_calls": [
                {"name": "bash", "args": {"command": "echo ok"}, "id": "q5-tool"}
            ],
        },
        {"content": "q5 done"},
    ]
    session._should_auto_compact = lambda: False
    await session.run(_long("q5"))
    assert not any(
        message.get("content") == "stale during finalization"
        for message in model.call_history[-1]["messages"]
    )


async def test_successful_turn_has_one_terminal_event_and_can_continue():
    session = _session(FakeClient(responses=["one", "two"]))
    seen: list = []
    session.subscribe(seen.append)

    await session.run("first")
    await session.run("second")

    terminal_events = [
        event
        for event in seen
        if event.type == EventType.TURN_END and event.metadata.get("run_outcome")
    ]
    assert len(terminal_events) == 2
    assert [event.metadata["run_outcome"] for event in terminal_events] == [
        "completed",
        "completed",
    ]
    assert all(event.metadata["commit_status"] == "committed" for event in terminal_events)
    assert session._runtime.phase is RunPhase.IDLE


async def test_core_listener_failure_does_not_fail_agent_run():
    agent = Agent(
        AgentContext(),
        AgentLoopConfig(model=ChatModelPort(FakeClient(response="ok"))),
    )

    def broken_listener(_event):
        raise RuntimeError("observer failed")

    agent.subscribe(broken_listener)
    messages = await agent.prompt("hello")

    assert [message.content for message in messages if message.role == "assistant"] == [
        "ok"
    ]
    assert agent.listener_errors
