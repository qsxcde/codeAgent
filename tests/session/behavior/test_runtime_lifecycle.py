from __future__ import annotations

import pytest

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.orchestration.config import AgentLoopConfig


def test_run_state_enforces_lifecycle_transitions() -> None:
    from codeagent.session.runtime.state import RunPhase, RunState

    state = RunState(run_id="run-1", session_id="session-1")

    state.transition(RunPhase.STARTING)
    state.transition(RunPhase.MODEL_WAIT)
    state.transition(RunPhase.COMPLETED)
    state.transition(RunPhase.FINALIZING)
    state.transition(RunPhase.IDLE)

    assert state.phase is RunPhase.IDLE

    with pytest.raises(ValueError, match="invalid run phase transition"):
        state.transition(RunPhase.TOOL_RUNNING)


def test_session_runtime_exposes_phase_and_run_correlation() -> None:
    from codeagent.session.runtime.controller import SessionRuntime
    from codeagent.session.runtime.state import RunPhase

    runtime = SessionRuntime(lambda event, run_id: None, session_id="session-1")
    run_id = runtime.start_run()

    assert runtime.phase is RunPhase.STARTING
    runtime.observe_event(
        AgentEvent(EventType.MESSAGE_START, run_id=run_id)
    )

    assert runtime.phase is RunPhase.MODEL_WAIT
    assert runtime.state.run_id == run_id
    assert runtime.state.session_id == "session-1"


def test_session_runtime_suppresses_events_after_run_finalization() -> None:
    from codeagent.session.runtime.controller import SessionRuntime
    from codeagent.session.runtime.state import RunPhase

    seen = []
    runtime = SessionRuntime(
        lambda event, run_id: None,
        event_handler=lambda event, run_id: seen.append(event),
    )
    run_id = runtime.start_run()
    runtime.finish_run(RunPhase.COMPLETED)

    runtime._handle_event(AgentEvent(EventType.MESSAGE_START), run_id)

    assert seen == []


def test_runtime_failure_classifies_recursion_limit_with_stable_fields() -> None:
    from codeagent.core.orchestration.loop import RecursionLimitError
    from codeagent.session.runtime.error_policy import classify_error
    from codeagent.session.runtime.state import RunPhase

    failure = classify_error(
        RecursionLimitError(),
        phase=RunPhase.CONTINUING,
        side_effect_state="possible",
        cleanup_uncertain=False,
    )

    assert failure.code == "recursion_limit"
    assert failure.phase == RunPhase.CONTINUING.value
    assert failure.retryable is False
    assert failure.side_effect_state == "possible"


@pytest.mark.parametrize(
    ("phase", "expected_code"),
    [
        ("tool_running", "tool_error"),
        ("awaiting_confirmation", "confirmation_error"),
        ("persistence", "persistence_error"),
        ("compaction", "compaction_failed"),
    ],
)
def test_runtime_failure_classifies_non_model_phases(
    phase: str, expected_code: str
) -> None:
    from codeagent.session.runtime.error_policy import classify_error

    failure = classify_error(RuntimeError("boom"), phase=phase)

    assert failure.code == expected_code
    assert failure.phase == phase
    assert failure.retryable is False


async def test_session_runtime_preserves_all_agent_loop_configuration() -> None:
    from codeagent.session.runtime.controller import SessionRuntime

    captured: list[AgentLoopConfig] = []

    class StubAgent:
        is_running = False

        def subscribe(self, listener):
            return lambda: None

        async def prompt(self, text):
            return []

    after = object()
    stop = object()
    config = AgentLoopConfig(
        model=object(),
        after_tool_call=after,
        tool_execution="sequential",
        should_stop_after_turn=stop,
    )

    runtime = SessionRuntime(
        lambda event, run_id: None,
        agent_factory=lambda context, agent_config, limit: (
            captured.append(agent_config) or StubAgent()
        ),
    )
    runtime.start_run()

    await runtime.execute(
        config,
        "hello",
        history=[],
        recursion_limit=1,
        tool_timeout=None,
    )

    assert captured[0].after_tool_call is after
    assert captured[0].tool_execution == "sequential"
    assert captured[0].should_stop_after_turn is stop


async def test_session_events_have_monotonic_run_sequences() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import ChatModelPort
    from codeagent.session import AgentSession, EventBus

    session = AgentSession(
        AgentLoopConfig(model=ChatModelPort(FakeClient(response="ok"))),
        EventBus(),
        session_id="session-1",
    )
    seen = []
    session.subscribe(seen.append)

    await session.run("hello")

    sequences = [event.metadata["sequence"] for event in seen if event.run_id is not None]
    assert sequences == list(range(1, len(sequences) + 1))


async def test_terminal_event_is_published_after_runtime_returns_idle() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import ChatModelPort
    from codeagent.session import AgentSession, EventBus

    session = AgentSession(
        AgentLoopConfig(model=ChatModelPort(FakeClient(response="ok"))),
        EventBus(),
    )
    observed_phases = []

    def observe(event) -> None:
        if event.type == EventType.TURN_END and event.metadata.get("run_outcome"):
            observed_phases.append(session._runtime.phase)

    session.subscribe(observe)
    await session.run("hello")

    from codeagent.session.runtime.state import RunPhase

    assert observed_phases == [RunPhase.IDLE]
