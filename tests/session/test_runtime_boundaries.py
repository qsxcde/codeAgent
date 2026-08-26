"""Behavioral tests for the split session runtime modules."""

from __future__ import annotations

import asyncio

import pytest

from codeagent.core.events import AgentEvent, EventType


def test_legacy_runtime_entrypoint_reexports_controller() -> None:
    from codeagent.session.runtime.controller import SessionRuntime
    from codeagent.session.session_runtime import SessionRuntime as LegacyRuntime

    assert LegacyRuntime is SessionRuntime


def test_runtime_accepts_an_injected_agent_factory() -> None:
    from codeagent.session.runtime.controller import SessionRuntime

    runtime = SessionRuntime(lambda event, run_id: None, agent_factory=lambda *args: None)

    assert runtime.agent_factory is not None


def test_runtime_rejects_a_second_active_run() -> None:
    from codeagent.session.runtime.controller import SessionRuntime

    runtime = SessionRuntime(lambda event, run_id: None)
    runtime.start_run()

    with pytest.raises(RuntimeError, match="already active"):
        runtime.start_run()


def test_runtime_clears_confirmation_responses_when_a_run_finishes() -> None:
    from codeagent.session.runtime.controller import SessionRuntime

    runtime = SessionRuntime(lambda event, run_id: None)
    runtime.start_run()
    runtime.respond_approval("stale", True)
    runtime.finish_run()

    assert runtime.confirm_queue.empty()


def test_confirmation_waits_for_matching_request_id() -> None:
    from codeagent.session.runtime.confirmation import ConfirmationCoordinator

    async def scenario() -> None:
        coordinator = ConfirmationCoordinator()
        waiter = asyncio.create_task(coordinator.wait("wanted"))
        coordinator.respond("other", True)
        await asyncio.sleep(0)
        assert not waiter.done()

        coordinator.respond("wanted", False)
        assert await waiter is False

    asyncio.run(scenario())


def test_event_mapper_preserves_tool_start_mapping() -> None:
    from codeagent.session.runtime.event_mapper import EventMapper

    mapped = EventMapper.map_agent_event(
        AgentEvent(
            EventType.TOOL_EXECUTION_START,
            payload={"tool_call_id": "call-1", "tool_name": "bash"},
        )
    )

    assert len(mapped) == 1
    assert mapped[0].type == EventType.TOOL_STARTED
    assert mapped[0].metadata == {
        "tool_call_id": "call-1",
        "tool_name": "bash",
    }


def test_error_policy_preserves_plain_exception_text() -> None:
    from codeagent.session.runtime.error_policy import friendly_error

    assert friendly_error(RuntimeError("boom")) == "boom"
