from __future__ import annotations

import pytest

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.session.runtime.controller import SessionRuntime
from codeagent.session.runtime.state import RunPhase


@pytest.mark.contract
def test_session_runtime_forwards_correlated_subagent_event_without_advancing_parent() -> None:
    seen: list[AgentEvent] = []
    runtime = SessionRuntime(
        lambda event, run_id: None,
        event_handler=lambda event, run_id: seen.append(event),
        session_id="parent-session",
    )
    parent_run_id = runtime.start_run()
    runtime.observe_event(AgentEvent(EventType.MESSAGE_START, run_id=parent_run_id))
    parent_phase = runtime.phase

    runtime._handle_event(
        AgentEvent(
            EventType.SUBAGENT_PROGRESS,
            payload={"child_event_type": EventType.MESSAGE_START},
            session_id="child-session",
            run_id="child-run-1",
            delegation_id="delegation-1",
            parent_run_id=parent_run_id,
            child_run_id="child-run-1",
            attempt_id="attempt-1",
            depth=1,
            subagent_status="running",
            child_phase="model_wait",
            child_event_type=EventType.MESSAGE_START,
            child_sequence=3,
        ),
        parent_run_id,
    )

    assert len(seen) == 1
    event = seen[0]
    assert event.type == EventType.SUBAGENT_PROGRESS
    assert event.run_id == "child-run-1"
    assert event.parent_run_id == parent_run_id
    assert event.session_id == "child-session"
    assert event.child_sequence == 3
    assert event.parent_sequence == event.metadata["parent_sequence"]
    assert event.parent_sequence is not None
    assert runtime.phase is parent_phase is RunPhase.MODEL_WAIT


@pytest.mark.contract
def test_session_runtime_keeps_legacy_run_filter_for_non_subagent_events() -> None:
    seen: list[AgentEvent] = []
    runtime = SessionRuntime(
        lambda event, run_id: None,
        event_handler=lambda event, run_id: seen.append(event),
        session_id="parent-session",
    )
    parent_run_id = runtime.start_run()

    runtime._handle_event(
        AgentEvent(EventType.MESSAGE_START, run_id="stale-child-run"),
        parent_run_id,
    )

    assert seen == []
