from __future__ import annotations

import math

import pytest

from codeagent.core.contracts.events import AgentEvent, EventType


def _public(name: str):
    import codeagent.core as public

    assert hasattr(public, name), f"codeagent.core is missing {name}"
    return getattr(public, name)


def _request(**overrides):
    budget_type = _public("SubagentBudget")
    context_type = _public("SubagentContextItem")
    request_type = _public("SubagentRequest")
    values = {
        "delegation_id": "delegation-1",
        "parent_run_id": "parent-run-1",
        "task": "inspect the repository",
        "profile": "read_only",
        "depth": 1,
        "max_depth": 1,
        "budget": budget_type(
            max_turns=3,
            max_tool_calls=5,
            timeout_seconds=30.0,
            max_output_chars=2_000,
        ),
        "context": (context_type("constraint", "do not modify files"),),
    }
    values.update(overrides)
    return request_type(**values)


def _failure(
    reason_code=None,
    *,
    phase=None,
    cleanup_uncertain: bool = False,
):
    reason_type = _public("SubagentReasonCode")
    phase_type = _public("SubagentFailurePhase")
    failure_type = _public("SubagentFailure")
    return failure_type(
        reason_code=reason_code or reason_type.EXECUTION_FAILED,
        message="subagent did not complete",
        phase=phase or phase_type.RUNNING,
        retryable=False,
        cleanup_uncertain=cleanup_uncertain,
    )


def _result(request, status, *, failure=None):
    result_type = _public("SubagentResult")
    status_type = _public("SubagentStatus")
    return result_type(
        delegation_id=request.delegation_id,
        status=status,
        child_run_id="child-run-1" if status is not status_type.REJECTED else None,
        attempt_id="attempt-1" if status is not status_type.REJECTED else None,
        summary="done" if status is status_type.COMPLETED else "",
        failure=failure,
    )


@pytest.mark.unit
def test_request_keeps_immutable_handoff_facts_and_budget() -> None:
    request = _request()

    assert request.delegation_id == "delegation-1"
    assert request.parent_run_id == "parent-run-1"
    assert request.context[0].kind == "constraint"
    assert request.budget.timeout_seconds == 30.0

    with pytest.raises((AttributeError, TypeError)):
        request.task = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_request_rejects_invalid_identity_task_depth_and_budget() -> None:
    request_type = _public("SubagentRequest")
    invalid_requests = (
        {"delegation_id": ""},
        {"parent_run_id": "  "},
        {"task": "\n"},
        {"depth": -1},
        {"max_depth": -1},
    )

    for override in invalid_requests:
        values = {
            "delegation_id": "delegation-1",
            "parent_run_id": "parent-run-1",
            "task": "inspect the repository",
        }
        values.update(override)
        with pytest.raises(_public("SubagentRequestError")) as raised:
            request_type(**values)
        assert raised.value.code == "invalid_request"

    with pytest.raises(_public("SubagentRequestError")) as raised:
        _public("SubagentBudget")(max_turns=0)
    assert raised.value.code == "invalid_request"

    with pytest.raises(_public("SubagentRequestError")) as raised:
        _request(depth=2, max_depth=1)
    assert raised.value.code == "depth_exceeded"


@pytest.mark.unit
def test_result_requires_terminal_status_and_structured_failure() -> None:
    request = _request()
    status_type = _public("SubagentStatus")
    result_type = _public("SubagentResult")

    with pytest.raises(ValueError, match="terminal"):
        _result(request, status_type.RUNNING)

    with pytest.raises(ValueError, match="failure"):
        _result(request, status_type.FAILED)

    with pytest.raises(ValueError, match="completed"):
        result_type(
            delegation_id=request.delegation_id,
            status=status_type.COMPLETED,
            summary="done",
            failure=_failure(),
        )


@pytest.mark.unit
def test_state_accepts_happy_path_and_keeps_child_identity() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    state = state_type(request)

    state.transition(status_type.QUEUED)
    state.transition(status_type.STARTING, attempt_id="attempt-1")
    state.transition(status_type.RUNNING, child_run_id="child-run-1")
    state.transition(status_type.COMPLETED, result=_result(request, status_type.COMPLETED))

    assert state.status is status_type.COMPLETED
    assert state.child_run_id == "child-run-1"
    assert state.attempt_id == "attempt-1"
    assert state.terminal_result is not None


@pytest.mark.unit
def test_state_supports_confirmation_and_cancellation_cleanup_paths() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    phase_type = _public("SubagentFailurePhase")
    state = state_type(request)
    state.transition(status_type.QUEUED)
    state.transition(status_type.STARTING, attempt_id="attempt-1")
    state.transition(status_type.RUNNING, child_run_id="child-run-1")
    state.transition(status_type.WAITING_CONFIRMATION)
    state.transition(status_type.RUNNING)
    state.transition(status_type.CANCELLING)

    result = _result(
        request,
        status_type.CANCELLED,
        failure=_failure(
            _public("SubagentReasonCode").PARENT_CANCELLED,
            phase=phase_type.CANCELLING,
            cleanup_uncertain=True,
        ),
    )
    state.transition(status_type.CANCELLED, result=result)

    assert state.status is status_type.CANCELLED
    assert state.terminal_result.failure is not None
    assert state.terminal_result.failure.cleanup_uncertain is True


@pytest.mark.unit
def test_queued_cancellation_does_not_create_child_run() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    phase_type = _public("SubagentFailurePhase")
    state = state_type(request)
    state.transition(status_type.QUEUED)
    state.transition(
        status_type.CANCELLED,
        result=_public("SubagentResult")(
            delegation_id=request.delegation_id,
            status=status_type.CANCELLED,
            failure=_failure(
                _public("SubagentReasonCode").PARENT_CANCELLED,
                phase=phase_type.QUEUE,
            ),
        ),
    )

    assert state.child_run_id is None
    assert state.status is status_type.CANCELLED


@pytest.mark.unit
def test_state_rejects_illegal_transition_and_conflicting_terminal_result() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    state_error = _public("SubagentStateError")
    state = state_type(request)

    with pytest.raises(state_error):
        state.transition(status_type.RUNNING)

    state.transition(status_type.QUEUED)
    completed = _result(request, status_type.COMPLETED)
    with pytest.raises(state_error):
        state.transition(status_type.COMPLETED, result=completed)

    state.transition(
        status_type.CANCELLED,
        result=_result(
            request,
            status_type.CANCELLED,
            failure=_failure(
                _public("SubagentReasonCode").PARENT_CANCELLED,
                phase=_public("SubagentFailurePhase").QUEUE,
            ),
        ),
    )
    with pytest.raises(state_error):
        state.transition(
            status_type.FAILED,
            result=_result(
                request,
                status_type.FAILED,
                failure=_failure(),
            ),
        )


@pytest.mark.unit
def test_state_rejects_a_non_result_terminal_payload() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    state = state_type(request)
    state.transition(status_type.QUEUED)
    state.transition(status_type.STARTING)
    state.transition(status_type.RUNNING)

    with pytest.raises(_public("SubagentStateError"), match="SubagentResult"):
        state.transition(status_type.COMPLETED, result=object())


@pytest.mark.unit
def test_state_rejects_preloaded_terminal_without_result() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")

    with pytest.raises(_public("SubagentStateError"), match="terminal result"):
        state_type(request, status=status_type.COMPLETED)


@pytest.mark.unit
def test_duplicate_identical_terminal_result_is_idempotent() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    state = state_type(request)
    state.transition(status_type.QUEUED)
    result = _public("SubagentResult")(
        delegation_id=request.delegation_id,
        status=status_type.CANCELLED,
        failure=_failure(_public("SubagentReasonCode").PARENT_CANCELLED),
    )

    state.transition(status_type.CANCELLED, result=result)
    state.transition(status_type.CANCELLED, result=result)

    assert state.terminal_result is result


@pytest.mark.unit
def test_budget_exhaustion_is_failed_reason_not_a_new_status() -> None:
    request = _request()
    status_type = _public("SubagentStatus")
    result = _result(
        request,
        status_type.FAILED,
        failure=_failure(
            _public("SubagentReasonCode").BUDGET_EXCEEDED,
        ),
    )

    assert result.status is status_type.FAILED
    assert result.failure.reason_code == _public("SubagentReasonCode").BUDGET_EXCEEDED


@pytest.mark.unit
def test_budget_rejects_non_finite_timeout() -> None:
    budget_type = _public("SubagentBudget")

    for timeout in (math.inf, math.nan, -math.inf):
        with pytest.raises(_public("SubagentRequestError")):
            budget_type(timeout_seconds=timeout)


@pytest.mark.unit
def test_result_retains_cleanup_uncertain_without_breaking_old_constructor() -> None:
    request = _request()
    result = _public("SubagentResult")(
        delegation_id=request.delegation_id,
        status=_public("SubagentStatus").COMPLETED,
        summary="done",
        cleanup_uncertain=True,
    )

    assert result.cleanup_uncertain is True


@pytest.mark.unit
def test_startup_failure_and_wall_clock_timeout_keep_distinct_outcomes() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    phase_type = _public("SubagentFailurePhase")
    reason_type = _public("SubagentReasonCode")

    failed_state = state_type(request)
    failed_state.transition(status_type.QUEUED)
    failed_state.transition(status_type.STARTING, attempt_id="attempt-1")
    failed_state.transition(
        status_type.FAILED,
        result=_result(
            request,
            status_type.FAILED,
            failure=_failure(reason_type.STARTUP_FAILED, phase=phase_type.STARTING),
        ),
    )

    timeout_state = state_type(request)
    timeout_state.transition(status_type.QUEUED)
    timeout_state.transition(status_type.STARTING, attempt_id="attempt-1")
    timeout_state.transition(status_type.RUNNING, child_run_id="child-run-1")
    timeout_state.transition(status_type.CANCELLING)
    timeout_state.transition(
        status_type.TIMED_OUT,
        result=_result(
            request,
            status_type.TIMED_OUT,
            failure=_failure(reason_type.TIMEOUT, phase=phase_type.CANCELLING),
        ),
    )

    assert failed_state.terminal_result.failure.reason_code == reason_type.STARTUP_FAILED
    assert timeout_state.status is status_type.TIMED_OUT
    assert timeout_state.terminal_result.failure.reason_code == reason_type.TIMEOUT


@pytest.mark.unit
def test_permission_rejection_happens_before_child_identity_exists() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    reason_type = _public("SubagentReasonCode")
    phase_type = _public("SubagentFailurePhase")
    state = state_type(request)

    state.transition(
        status_type.REJECTED,
        result=_public("SubagentResult")(
            delegation_id=request.delegation_id,
            status=status_type.REJECTED,
            failure=_failure(reason_type.PERMISSION_DENIED, phase=phase_type.VALIDATION),
        ),
    )

    assert state.child_run_id is None
    assert state.terminal_result.failure.reason_code == reason_type.PERMISSION_DENIED


@pytest.mark.unit
def test_retry_uses_a_new_attempt_without_mutating_the_failed_attempt() -> None:
    request = _request()
    state_type = _public("SubagentState")
    status_type = _public("SubagentStatus")
    reason_type = _public("SubagentReasonCode")
    phase_type = _public("SubagentFailurePhase")

    first = state_type(request)
    first.transition(status_type.QUEUED)
    first.transition(status_type.STARTING, attempt_id="attempt-1")
    first.transition(status_type.RUNNING, child_run_id="child-run-1")
    first.transition(
        status_type.FAILED,
        result=_result(
            request,
            status_type.FAILED,
            failure=_failure(reason_type.EXECUTION_FAILED, phase=phase_type.RUNNING),
        ),
    )

    retry = state_type(request)
    retry.transition(status_type.QUEUED)
    retry.transition(status_type.STARTING, attempt_id="attempt-2")
    retry.transition(status_type.RUNNING, child_run_id="child-run-2")

    assert first.attempt_id == "attempt-1"
    assert first.child_run_id == "child-run-1"
    assert retry.attempt_id == "attempt-2"
    assert retry.child_run_id == "child-run-2"


@pytest.mark.unit
async def test_fake_runner_can_implement_provider_neutral_port() -> None:
    runner_type = _public("SubagentRunner")

    class FakeRunner:
        async def execute(self, request, *, on_event=None):
            return _result(request, _public("SubagentStatus").COMPLETED)

        async def cancel(self, delegation_id):
            return delegation_id == "delegation-1"

    runner = FakeRunner()
    assert isinstance(runner, runner_type)
    result = await runner.execute(_request())
    assert result.status is _public("SubagentStatus").COMPLETED
    assert await runner.cancel("delegation-1") is True
    assert await runner.cancel("other") is False


@pytest.mark.contract
def test_agent_event_exposes_optional_parent_child_correlation() -> None:
    fields = AgentEvent.__dataclass_fields__
    assert {
        "delegation_id",
        "parent_run_id",
        "child_run_id",
        "attempt_id",
        "depth",
        "subagent_status",
        "child_phase",
    } <= fields.keys()

    event = AgentEvent(
        EventType.TOOL_EXECUTION_START,
        run_id="child-run-1",
        delegation_id="delegation-1",
        parent_run_id="parent-run-1",
        child_run_id="child-run-1",
        attempt_id="attempt-1",
        depth=1,
        subagent_status=_public("SubagentStatus").RUNNING,
        child_phase="tool_running",
    )

    assert event.run_id == "child-run-1"
    assert event.parent_run_id == "parent-run-1"
    assert event.child_run_id == "child-run-1"
    assert event.subagent_status is _public("SubagentStatus").RUNNING
    assert event.metadata["delegation_id"] == "delegation-1"
    assert event.metadata["depth"] == 1


@pytest.mark.contract
def test_parent_event_keeps_parent_run_id_when_linking_child() -> None:
    event = AgentEvent(
        EventType.TOOL_EXECUTION_START,
        run_id="parent-run-1",
        delegation_id="delegation-1",
        parent_run_id="parent-run-1",
        child_run_id="child-run-1",
        subagent_status=_public("SubagentStatus").STARTING,
    )

    assert event.run_id == event.parent_run_id == "parent-run-1"
    assert event.child_run_id == "child-run-1"
    assert event.metadata["parent_run_id"] == "parent-run-1"


@pytest.mark.contract
def test_agent_event_hydrates_correlation_from_legacy_metadata() -> None:
    event = AgentEvent(
        EventType.TOOL_EXECUTION_UPDATE,
        metadata={
            "delegation_id": "delegation-1",
            "parent_run_id": "parent-run-1",
            "child_run_id": "child-run-1",
            "attempt_id": "attempt-1",
            "depth": 1,
            "subagent_status": "running",
            "child_phase": "tool_running",
        },
        run_id="child-run-1",
    )

    assert event.delegation_id == "delegation-1"
    assert event.parent_run_id == "parent-run-1"
    assert event.child_run_id == "child-run-1"
    assert event.attempt_id == "attempt-1"
    assert event.depth == 1
    assert event.subagent_status == "running"
    assert event.child_phase == "tool_running"


@pytest.mark.contract
def test_core_facade_exports_subagent_contract_identity() -> None:
    import codeagent.core.contracts as contracts
    import codeagent.core as public

    for name in (
        "SubagentStatus",
        "SubagentRequest",
        "SubagentResult",
        "SubagentState",
        "SubagentRunner",
    ):
        assert getattr(public, name) is getattr(contracts, name)
