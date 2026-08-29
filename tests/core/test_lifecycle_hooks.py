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
