from __future__ import annotations

import asyncio

import pytest

from codeagent.core import AgentEvent, AgentLoopConfig, EventType, LifecycleHookEvent
from codeagent.app.container import ChatModelPort
from codeagent.ai.providers.fake import FakeClient
from codeagent.session import AgentSession, EventBus
from codeagent.session.persistence import MemoryStore
from codeagent.session.runtime.state import RunPhase


class _EchoTool:
    name = "echo"
    description = "echo"
    parameters = {"type": "object"}

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        return "ok"


async def test_session_lifecycle_hooks_cover_all_scopes_with_correlation() -> None:
    observed: list[LifecycleHookEvent] = []
    config = AgentLoopConfig(
        model=ChatModelPort(FakeClient(response="ok")),
        lifecycle_hooks=[observed.append],
    )
    session = AgentSession(config, EventBus(), session_id="session-1")

    await session.run("hello")

    scopes = {event.scope for event in observed}
    assert scopes == {"session", "turn", "model"}
    session_events = [event for event in observed if event.scope == "session"]
    assert [event.phase for event in session_events[:1]] == ["started"]
    assert session_events[-1].phase == "finished"
    assert all(event.session_id == "session-1" for event in session_events)
    assert all(event.run_id for event in observed)
    assert [message.content for message in session.history] == ["hello", "ok"]


async def test_session_lifecycle_hooks_observe_tool_scope_without_mutating_events() -> None:
    observed: list[LifecycleHookEvent] = []
    tool = _EchoTool()
    config = AgentLoopConfig(
        model=ChatModelPort(
            FakeClient(
                steps=[
                    {
                        "content": "",
                        "tool_calls": [
                            {"name": "echo", "args": {"value": "ok"}, "id": "call-1"}
                        ],
                    },
                    {"content": "done"},
                ]
            )
        ),
        tools=[tool],
        lifecycle_hooks=[observed.append],
    )
    session = AgentSession(config, EventBus(), session_id="session-2")

    await session.run("use tool")

    tool_events = [event for event in observed if event.scope == "tool"]
    assert [event.phase for event in tool_events] == ["updated", "started", "finished"]
    assert all(event.event.tool_call_id == "call-1" for event in tool_events)
    assert [message.content for message in session.history][-1] == "done"


async def test_session_hook_diagnostics_cover_core_and_session_without_persistence() -> None:
    def broken_session(event: LifecycleHookEvent) -> None:
        if event.scope == "session":
            raise ValueError("session observer failed")

    async def broken_core(event: LifecycleHookEvent) -> None:
        if event.scope == "turn":
            raise RuntimeError("core observer failed")

    store = MemoryStore()
    config = AgentLoopConfig(
        model=ChatModelPort(FakeClient(response="ok")),
        lifecycle_hooks=[broken_session, broken_core],
    )
    session = AgentSession(config, EventBus(), store=store, session_id="hook-diagnostics")

    await session.run("hello")

    diagnostics = session.lifecycle_hook_diagnostics
    assert any(item.scope == "session" and item.stage == "invoke" for item in diagnostics)
    assert any(item.scope == "turn" and item.stage == "await" for item in diagnostics)
    assert all(item.session_id == "hook-diagnostics" for item in diagnostics)
    assert all(item.run_id for item in diagnostics)
    assert [message.content for message in session.history] == ["hello", "ok"]
    assert [message.content for message in store.load_messages("hook-diagnostics")] == [
        "hello",
        "ok",
    ]
    assert all("observer failed" not in (message.content or "") for message in session.history)


async def test_session_cancellation_cleans_pending_async_hook_tasks() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocking_hook(_event: LifecycleHookEvent) -> None:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    session = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(FakeClient(response="ok")),
            lifecycle_hooks=[blocking_hook],
        ),
        EventBus(),
    )
    running = asyncio.create_task(session.run("cancel me"))
    await started.wait()

    session.abort()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert cancelled.is_set()
    assert not session._lifecycle_hook_tasks
    assert session.lifecycle_hook_diagnostics == []
    assert session.last_outcome is not None
    assert session.last_outcome.phase is RunPhase.CANCELLED


async def test_session_uncopyable_hook_snapshot_isolated_from_event_bus() -> None:
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise TypeError("payload cannot be copied")

    observed: list[LifecycleHookEvent] = []
    published: list[AgentEvent] = []
    session = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(FakeClient(response="ok")),
            lifecycle_hooks=[observed.append],
        ),
        EventBus(),
        session_id="session-snapshot-failure",
    )
    session.subscribe(published.append)

    session._emit(
        AgentEvent(EventType.MESSAGE_UPDATE, payload=Uncopyable()),
        run_id=None,
    )

    assert published
    assert observed == []
    diagnostics = session.lifecycle_hook_diagnostics
    assert len(diagnostics) == 1
    assert diagnostics[0].stage == "snapshot"
    assert diagnostics[0].scope == "session"
    assert diagnostics[0].phase == "updated"
    assert diagnostics[0].event_type == EventType.MESSAGE_UPDATE
