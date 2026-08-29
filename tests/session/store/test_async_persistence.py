from __future__ import annotations

import asyncio
import threading
import time

import pytest

from codeagent.core.contracts.messages import Message
from codeagent.session.persistence.async_boundary import AsyncPersistenceBoundary
from codeagent.session.persistence.memory_store import MemoryStore
from codeagent.session.session_persistence import SessionPersistence
from codeagent.session.persistence.models import UsageStats


class _SlowMemoryStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.commit_thread_id: int | None = None

    def commit_turn(self, session_id, messages, usage, *, context_tokens):
        self.commit_thread_id = threading.get_ident()
        time.sleep(0.05)
        return super().commit_turn(
            session_id,
            messages,
            usage,
            context_tokens=context_tokens,
        )


async def test_persistence_boundary_offloads_sync_operation() -> None:
    boundary = AsyncPersistenceBoundary()
    main_thread_id = threading.get_ident()

    def operation() -> tuple[int, str]:
        time.sleep(0.05)
        return threading.get_ident(), "done"

    task = asyncio.create_task(boundary.run(operation))
    await asyncio.sleep(0.01)

    assert not task.done()
    worker_thread_id, result = await task
    assert worker_thread_id != main_thread_id
    assert result == "done"


async def test_persistence_boundary_waits_for_cancelled_operation() -> None:
    boundary = AsyncPersistenceBoundary()
    started = threading.Event()
    release = threading.Event()

    def operation() -> str:
        started.set()
        release.wait(timeout=1)
        return "committed"

    task = asyncio.create_task(boundary.run(operation))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    await asyncio.sleep(0)

    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_session_persistence_commits_through_async_boundary() -> None:
    store = _SlowMemoryStore()
    store.create("async-session")
    persistence = SessionPersistence(store, "async-session")

    task = asyncio.create_task(
        persistence.commit_turn_async(
            [Message(role="user", content="hello")],
            UsageStats(input_tokens=1),
            context_tokens=1,
        )
    )
    await asyncio.sleep(0.01)

    assert not task.done()
    await task
    assert store.commit_thread_id != threading.get_ident()
    assert [message.content for message in store.load_messages("async-session")] == [
        "hello"
    ]
