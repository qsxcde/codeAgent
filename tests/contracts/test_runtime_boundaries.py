"""Behavioral tests for the split session runtime modules."""

from __future__ import annotations

import asyncio

import pytest

from codeagent.core.contracts.events import AgentEvent, EventType


def test_runtime_entrypoint_is_the_canonical_controller() -> None:
    from codeagent.session.runtime import SessionRuntime
    from codeagent.session.runtime.controller import SessionRuntime as Controller

    assert SessionRuntime is Controller


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


async def test_confirmation_waits_for_matching_request_id() -> None:
    from codeagent.session.runtime.confirmation import ConfirmationCoordinator

    async def scenario() -> None:
        coordinator = ConfirmationCoordinator()
        waiter = asyncio.create_task(coordinator.wait("wanted"))
        coordinator.respond("other", True)
        await asyncio.sleep(0)
        assert not waiter.done()

        coordinator.respond("wanted", False)
        assert await waiter is False

    await (scenario())


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


def test_event_mapper_preserves_structured_runtime_correlation() -> None:
    from codeagent.session.runtime.event_mapper import EventMapper

    mapped = EventMapper.map_agent_event(
        AgentEvent(
            EventType.TOOL_EXECUTION_START,
            payload={"tool_call_id": "call-1", "tool_name": "bash"},
            metadata={"run_id": "run-1", "phase": "tool_running"},
            run_id="run-1",
            operation_id="op-1",
            phase="tool_running",
        )
    )

    assert mapped[0].run_id == "run-1"
    assert mapped[0].operation_id == "op-1"
    assert mapped[0].phase == "tool_running"
    assert mapped[0].metadata["run_id"] == "run-1"
    assert mapped[0].metadata["phase"] == "tool_running"


def test_event_mapper_assigns_stable_tool_error_code() -> None:
    from codeagent.core.contracts.messages import ToolExecutionStatus, ToolResult
    from codeagent.session.runtime.event_mapper import EventMapper

    mapped = EventMapper.map_agent_event(
        AgentEvent(
            EventType.TOOL_EXECUTION_END,
            payload=ToolResult(
                "call-1",
                "拒绝",
                error=True,
                rejected=True,
                status=ToolExecutionStatus.REJECTED,
                operation_id="op-1",
            ),
        )
    )

    assert mapped[0].error_code == "confirmation_rejected"
    assert mapped[0].metadata["error_code"] == "confirmation_rejected"


def test_event_mapper_propagates_structured_tool_output_facts() -> None:
    from codeagent.core.contracts.messages import (
        OutputCompleteness,
        ToolOutputMetadata,
        ToolResult,
    )
    from codeagent.session.runtime.event_mapper import EventMapper

    metadata = ToolOutputMetadata(
        completeness=OutputCompleteness.TRUNCATED,
        total_bytes=100,
        total_lines=20,
        shown_lines=4,
        truncated_by="tool_bytes",
        path="README.md",
    )
    mapped = EventMapper.map_agent_event(
        AgentEvent(
            EventType.TOOL_EXECUTION_END,
            payload=ToolResult("call-1", "bounded", output_metadata=metadata),
        )
    )

    assert len(mapped) == 2
    assert mapped[0].metadata["output_metadata"] == metadata.to_dict()
    assert mapped[1].metadata["total_bytes"] == 100
    assert mapped[1].metadata["truncated_by"] == "tool_bytes"


def test_error_policy_preserves_plain_exception_text() -> None:
    from codeagent.session.runtime.error_policy import friendly_error

    assert friendly_error(RuntimeError("boom")) == "boom"
