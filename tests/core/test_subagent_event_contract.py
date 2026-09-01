from __future__ import annotations

import pytest

from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import ToolCall, ToolResult
from codeagent.core.execution.runtime import ToolExecutionRuntime
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.core.orchestration.tool_call import new_tool_result
from codeagent.core.contracts.errors import SubagentStateError
from codeagent.core.contracts.subagent_state import SubagentState
from codeagent.core.contracts.subagents import (
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
)


@pytest.mark.contract
def test_subagent_event_contract_keeps_correlation_and_two_sequences() -> None:
    event = AgentEvent(
        EventType.SUBAGENT_PROGRESS,
        payload={"tool_name": "read", "status": "running"},
        run_id="child-run-1",
        delegation_id="delegation-1",
        parent_run_id="parent-run-1",
        child_run_id="child-run-1",
        attempt_id="attempt-1",
        depth=1,
        subagent_status="running",
        child_phase="tool_running",
        child_event_type=EventType.TOOL_STARTED,
        child_sequence=4,
        parent_sequence=12,
    )

    assert {
        EventType.SUBAGENT_QUEUED,
        EventType.SUBAGENT_STARTED,
        EventType.SUBAGENT_PROGRESS,
        EventType.SUBAGENT_FINISHED,
    } <= set(vars(EventType).values())
    assert event.run_id == event.child_run_id
    assert event.parent_run_id == "parent-run-1"
    assert event.child_sequence == 4
    assert event.parent_sequence == 12
    assert event.metadata["child_event_type"] == EventType.TOOL_STARTED
    assert event.metadata["child_sequence"] == 4
    assert event.metadata["parent_sequence"] == 12


@pytest.mark.contract
def test_subagent_event_contract_hydrates_new_fields_from_metadata() -> None:
    event = AgentEvent(
        EventType.SUBAGENT_PROGRESS,
        run_id="child-run-1",
        metadata={
            "delegation_id": "delegation-1",
            "parent_run_id": "parent-run-1",
            "child_run_id": "child-run-1",
            "attempt_id": "attempt-1",
            "depth": 1,
            "subagent_status": "waiting_confirmation",
            "child_phase": "awaiting_confirmation",
            "child_event_type": EventType.CONFIRMATION_REQUESTED,
            "child_sequence": 8,
            "parent_sequence": 20,
        },
    )

    assert event.child_event_type == EventType.CONFIRMATION_REQUESTED
    assert event.child_sequence == 8
    assert event.parent_sequence == 20
    assert event.subagent_status == "waiting_confirmation"


@pytest.mark.contract
def test_subagent_state_commits_one_terminal_result_and_keeps_legacy_events() -> None:
    request = SubagentRequest(
        delegation_id="delegation-state",
        parent_run_id="parent-run-1",
        task="inspect",
    )
    state = SubagentState(request)
    state.transition(SubagentStatus.QUEUED)
    state.transition(SubagentStatus.STARTING, attempt_id="attempt-1")
    state.transition(SubagentStatus.RUNNING, child_run_id="child-run-1")
    state.transition(SubagentStatus.WAITING_CONFIRMATION)
    state.transition(SubagentStatus.RUNNING)
    result = SubagentResult(
        delegation_id=request.delegation_id,
        status=SubagentStatus.COMPLETED,
        child_run_id="child-run-1",
        attempt_id="attempt-1",
        summary="done",
    )

    state.finish(result)
    state.transition(SubagentStatus.COMPLETED, result=result)

    assert state.terminal_emitted is True
    assert state.terminal_result == result
    with pytest.raises(SubagentStateError, match="conflicting"):
        state.transition(
            SubagentStatus.COMPLETED,
            result=SubagentResult(
                delegation_id=request.delegation_id,
                status=SubagentStatus.COMPLETED,
                child_run_id="child-run-1",
                attempt_id="attempt-1",
                summary="different",
            ),
        )

    legacy = AgentEvent(
        EventType.TOOL_PROGRESS,
        payload={"elapsed_ms": 10},
        metadata={"tool_call_id": "tool-1", "run_id": "parent-run-1"},
    )
    assert legacy.metadata["tool_call_id"] == "tool-1"


@pytest.mark.unit
async def test_core_tool_bridge_forwards_structured_subagent_events_directly() -> None:
    class EventTool:
        name = "delegate"
        description = "delegate"
        parameters = {"type": "object"}

        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            del arguments, signal
            await on_update(
                AgentEvent(
                    EventType.SUBAGENT_PROGRESS,
                    payload={"child_event_type": EventType.MESSAGE_START},
                    run_id="child-run-1",
                    delegation_id="delegation-1",
                    parent_run_id="parent-run-1",
                    child_run_id="child-run-1",
                    child_sequence=2,
                )
            )
            return ToolResult(tool_call_id, "delegate complete", name=self.name)

    events: list[AgentEvent] = []
    result = await new_tool_result(
        EventTool(),
        ToolCall("call-1", "delegate", {}),
        AgentContext(),
            AgentLoopConfig(model=object(), tools=[], tool_runtime=ToolExecutionRuntime()),
        events.append,
        operation_id="operation-1",
    )

    assert result.error is False
    forwarded = [event for event in events if event.type == EventType.SUBAGENT_PROGRESS]
    assert len(forwarded) == 1
    assert forwarded[0].run_id == "child-run-1"
    assert all(event.type != EventType.TOOL_EXECUTION_UPDATE for event in events)
