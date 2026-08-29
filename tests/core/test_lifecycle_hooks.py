from __future__ import annotations

import asyncio
from typing import Any

import pytest

from codeagent.core import (
    Agent,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    StreamEvent,
    run_agent_loop,
)
from codeagent.core.contracts.hooks import (
    HookDiagnostic,
    LifecycleHookEvent,
    to_lifecycle_hook_event,
)


class _Model:
    model_id = "hook-test-model"

    def stream(self, messages, tools=None):
        async def iterator():
            yield StreamEvent(type="content", text="reply")
            yield StreamEvent(type="finish", finish_reason="stop")

        return iterator()


class _FailingModel(_Model):
    def stream(self, messages, tools=None):
        async def iterator():
            raise RuntimeError("model unavailable")
            yield StreamEvent(type="finish")

        return iterator()


class _GatedModel(_Model):
    def __init__(self):
        self.started = asyncio.Event()

    def stream(self, messages, tools=None):
        async def iterator():
            self.started.set()
            await asyncio.Future()
            yield StreamEvent(type="content", text="unreachable")

        return iterator()


def test_lifecycle_hook_event_contains_explicit_scope_and_detached_event() -> None:
    source = AgentEvent(
        "message_update",
        payload={"nested": ["original"]},
        metadata={"run_id": "run-1"},
        run_id="run-1",
    )

    observed = to_lifecycle_hook_event(
        source,
        scope="model",
        phase="updated",
        session_id="session-1",
    )

    assert isinstance(observed, LifecycleHookEvent)
    assert observed.scope == "model"
    assert observed.phase == "updated"
    assert observed.run_id == "run-1"
    assert observed.session_id == "session-1"
    assert observed.event is not source
    observed.event.payload["nested"].append("hook mutation")
    observed.event.metadata["changed"] = True
    assert source.payload == {"nested": ["original"]}
    assert "changed" not in source.metadata


async def test_configured_hooks_are_ordered_and_return_values_are_ignored() -> None:
    seen: list[tuple[str, str, str]] = []

    def first(event: LifecycleHookEvent) -> Any:
        seen.append(("first", event.scope, event.phase))
        return {"action": "block"}

    def second(event: LifecycleHookEvent) -> Any:
        seen.append(("second", event.scope, event.phase))
        return False

    agent = Agent(
        AgentContext(),
        AgentLoopConfig(model=_Model(), lifecycle_hooks=[first, second]),
        run_id="run-1",
    )

    await agent.prompt("hello")

    assert seen[:4] == [
        ("first", "turn", "started"),
        ("second", "turn", "started"),
        ("first", "model", "started"),
        ("second", "model", "started"),
    ]
    assert ("first", "model", "finished") in seen
    assert ("second", "turn", "finished") in seen
    assert [message.content for message in agent.context.messages] == ["hello", "reply"]


async def test_hook_failures_are_structured_and_do_not_affect_agent_run() -> None:
    observed: list[tuple[str, str]] = []

    def broken_sync(event: LifecycleHookEvent) -> None:
        if event.event_type == "turn_start":
            raise ValueError("sync observer failed")

    async def broken_async(event: LifecycleHookEvent) -> None:
        if event.event_type == "turn_start":
            raise RuntimeError("async observer failed")

    def healthy(event: LifecycleHookEvent) -> None:
        observed.append((event.event_type, event.phase))

    agent = Agent(
        AgentContext(),
        AgentLoopConfig(
            model=_Model(),
            lifecycle_hooks=[broken_sync, broken_async, healthy],
        ),
        run_id="run-hook-failure",
    )

    await agent.prompt("hello")

    assert [message.content for message in agent.context.messages] == ["hello", "reply"]
    assert ("turn_start", "started") in observed
    diagnostics = [
        item for item in agent.hook_diagnostics if item.event_type == "turn_start"
    ]
    assert len(diagnostics) == 2
    assert all(isinstance(item, HookDiagnostic) for item in diagnostics)
    assert {item.stage for item in diagnostics} == {"invoke", "await"}
    assert {item.error_type for item in diagnostics} == {"ValueError", "RuntimeError"}
    assert all(item.scope == "turn" for item in diagnostics)
    assert all(item.phase == "started" for item in diagnostics)
    assert all(item.run_id == "run-hook-failure" for item in diagnostics)
    assert all(item.hook_name != "<unknown>" for item in diagnostics)
    assert diagnostics[0].as_metadata()["code"] == "hook_failed"


async def test_uncopyable_hook_snapshot_isolated_from_agent_events() -> None:
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise TypeError("payload cannot be copied")

    observed: list[LifecycleHookEvent] = []
    received: list[AgentEvent] = []
    agent = Agent(
        AgentContext(),
        AgentLoopConfig(model=_Model(), lifecycle_hooks=[observed.append]),
        run_id="run-snapshot-failure",
    )
    agent.subscribe(received.append)

    event = AgentEvent("message_update", payload=Uncopyable())
    agent._emit(event)

    assert received
    assert observed == []
    assert len(agent.hook_diagnostics) == 1
    diagnostic = agent.hook_diagnostics[0]
    assert diagnostic.stage == "snapshot"
    assert diagnostic.hook_name == "event_snapshot"
    assert diagnostic.event_type == "message_update"
    assert diagnostic.scope == "model"
    assert diagnostic.phase == "updated"


async def test_cancelled_hook_is_not_reported_as_failure() -> None:
    async def cancelled(_event: LifecycleHookEvent) -> None:
        raise asyncio.CancelledError

    agent = Agent(
        AgentContext(),
        AgentLoopConfig(model=_Model(), lifecycle_hooks=[cancelled]),
    )

    await agent.prompt("hello")

    assert agent.hook_diagnostics == []


async def test_hook_failure_does_not_mask_agent_failure() -> None:
    def broken(_event: LifecycleHookEvent) -> None:
        raise RuntimeError("observer failed")

    agent = Agent(
        AgentContext(),
        AgentLoopConfig(model=_FailingModel(), lifecycle_hooks=[broken]),
        run_id="run-failed-with-hook",
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        await agent.prompt("hello")

    assert agent.hook_diagnostics
    assert all(item.error_type == "RuntimeError" for item in agent.hook_diagnostics)


@pytest.mark.parametrize(
    ("model", "expected_status"),
    [(_Model(), "completed"), (_FailingModel(), "failed")],
)
async def test_model_request_boundaries_are_emitted_once(model, expected_status) -> None:
    events: list[AgentEvent] = []

    if expected_status == "failed":
        with pytest.raises(RuntimeError, match="model unavailable"):
            await run_agent_loop(AgentContext(), AgentLoopConfig(model=model), "hello", emit=events.append)
    else:
        await run_agent_loop(AgentContext(), AgentLoopConfig(model=model), "hello", emit=events.append)

    started = [event for event in events if event.type == "model_request_started"]
    finished = [event for event in events if event.type == "model_request_finished"]
    assert len(started) == len(finished) == 1
    assert finished[0].metadata["status"] == expected_status


async def test_cancelled_model_request_emits_one_cancelled_finished_event() -> None:
    model = _GatedModel()
    events: list[AgentEvent] = []
    running = asyncio.create_task(
        run_agent_loop(AgentContext(), AgentLoopConfig(model=model), "hello", emit=events.append)
    )
    await model.started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    finished = [event for event in events if event.type == "model_request_finished"]
    assert len(finished) == 1
    assert finished[0].metadata["status"] == "cancelled"
