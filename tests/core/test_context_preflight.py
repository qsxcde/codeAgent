from __future__ import annotations

import math

import pytest

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context import preflight as context_preflight
from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.errors import ContextPreflightError
from codeagent.core.contracts.events import EventType
from codeagent.core.orchestration.loop import run_agent_loop
from codeagent.core.contracts.ports import StreamEvent
from codeagent.core.orchestration.config import AgentLoopConfig


def _snapshot(*, headroom: int, status: str = "estimate") -> ContextBudgetSnapshot:
    input_budget = 10_000
    return ContextBudgetSnapshot(
        context_window=12_000,
        output_reserve=1_000,
        reserve_tokens=1_000,
        input_budget=input_budget,
        system_prompt_tokens=0,
        tool_definitions_tokens=0,
        conversation_tokens=max(0, input_budget - headroom),
        tool_result_tokens=0,
        input_tokens=max(0, input_budget - headroom),
        headroom=headroom,
        status=status,
        window_source="catalog" if status == "estimate" else "fallback",
    )


def _policy(**kwargs):
    policy = getattr(context_preflight, "ContextPreflightConfig", None)
    assert policy is not None, "ContextPreflightConfig has not been implemented"
    return policy(**kwargs)


def _evaluate(snapshot, policy, **kwargs):
    evaluate = getattr(context_preflight, "evaluate_context_preflight", None)
    assert evaluate is not None, "evaluate_context_preflight has not been implemented"
    return evaluate(snapshot, policy, **kwargs)


def test_preflight_classifies_safe_near_limit_and_over_limit():
    policy = _policy(warning_headroom_tokens=1_000)

    safe = _evaluate(_snapshot(headroom=1_001), policy)
    near = _evaluate(_snapshot(headroom=1_000), policy)
    over = _evaluate(_snapshot(headroom=-1), policy)

    assert (safe.status, safe.allowed) == ("safe", True)
    assert (near.status, near.allowed) == ("near_limit", True)
    assert (over.status, over.allowed) == ("over_limit", False)
    assert over.snapshot.headroom == -1
    assert over.reason


def test_preflight_supports_ratio_threshold():
    policy = _policy(warning_headroom_tokens=None, warning_headroom_ratio=0.1)

    near = _evaluate(_snapshot(headroom=1_000), policy)
    safe = _evaluate(_snapshot(headroom=1_001), policy)

    assert near.status == "near_limit"
    assert safe.status == "safe"


def test_preflight_rejects_invalid_threshold_configuration():
    with pytest.raises(ValueError):
        _policy(warning_headroom_tokens=-1)
    with pytest.raises(ValueError):
        _policy(warning_headroom_tokens=1, warning_headroom_ratio=0.1)
    with pytest.raises(ValueError):
        _policy(warning_headroom_tokens=None, warning_headroom_ratio=math.nan)
    with pytest.raises(ValueError):
        _policy(warning_headroom_tokens=None, warning_headroom_ratio=0)


def test_preflight_applies_uncertain_budget_policy_without_mutating_snapshot():
    snapshot = _snapshot(headroom=-10, status="uncertain")
    policy = _policy(warning_headroom_tokens=1_000)

    allowed = _evaluate(snapshot, policy, uncertain_budget_policy="allow")
    blocked = _evaluate(snapshot, policy, uncertain_budget_policy="fail")

    assert (allowed.status, allowed.allowed) == ("uncertain", True)
    assert (blocked.status, blocked.allowed) == ("uncertain", False)
    assert allowed.snapshot == snapshot
    assert blocked.snapshot == snapshot


class _DescriptorModel:
    model_id = "preflight-test-model"

    def __init__(self, snapshot: ContextBudgetSnapshot, events=None):
        self.snapshot = snapshot
        self.events = events
        self.stream_calls = 0
        self.describe_calls = 0

    def describe_context_budget(self, messages, tools=None):
        self.describe_calls += 1
        return self.snapshot

    def stream(self, messages, tools=None):
        self.stream_calls += 1

        async def iterator():
            yield StreamEvent(type="content", text="ok")

        return iterator()


@pytest.mark.asyncio
async def test_over_limit_blocks_before_model_and_emits_structured_diagnostics():
    model = _DescriptorModel(_snapshot(headroom=-1))
    events = []

    with pytest.raises(ContextPreflightError) as raised:
        await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(model=model),
            "prompt",
            emit=events.append,
        )

    assert raised.value.code == "context_budget_exceeded"
    assert model.stream_calls == 0
    preflight = next(event for event in events if event.type == EventType.CONTEXT_PREFLIGHT)
    assert preflight.payload.status == "over_limit"
    error = next(event for event in events if event.type == EventType.ERROR)
    assert error.metadata == {
        **error.metadata,
        "error_code": "context_budget_exceeded",
        "phase": "context_preflight",
        "budget_status": "over_limit",
        "budget_allowed": False,
        "input_tokens": 10001,
        "input_budget": 10000,
        "headroom": -1,
        "window_source": "catalog",
        "warning_boundary": 2048,
    }


@pytest.mark.asyncio
async def test_near_limit_allows_model_request_and_publishes_preflight():
    model = _DescriptorModel(_snapshot(headroom=2_048))
    events = []

    result = await run_agent_loop(
        AgentContext(),
        AgentLoopConfig(model=model),
        "prompt",
        emit=events.append,
    )

    assert [message.content for message in result] == ["prompt", "ok"]
    assert model.stream_calls == 1
    preflight = next(event for event in events if event.type == EventType.CONTEXT_PREFLIGHT)
    assert (preflight.payload.status, preflight.payload.allowed) == (
        "near_limit",
        True,
    )


@pytest.mark.asyncio
async def test_uncertain_allow_calls_model_but_fail_blocks_before_model():
    allowed_model = _DescriptorModel(_snapshot(headroom=-1, status="uncertain"))
    allowed_events = []
    await run_agent_loop(
        AgentContext(),
        AgentLoopConfig(model=allowed_model, uncertain_budget_policy="allow"),
        "prompt",
        emit=allowed_events.append,
    )
    assert allowed_model.stream_calls == 1
    allowed_preflight = next(
        event for event in allowed_events if event.type == EventType.CONTEXT_PREFLIGHT
    )
    assert (allowed_preflight.payload.status, allowed_preflight.payload.allowed) == (
        "uncertain",
        True,
    )

    blocked_model = _DescriptorModel(_snapshot(headroom=-1, status="uncertain"))
    blocked_events = []
    with pytest.raises(ContextPreflightError) as raised:
        await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(model=blocked_model, uncertain_budget_policy="fail"),
            "prompt",
            emit=blocked_events.append,
        )
    assert raised.value.code == "context_budget_uncertain"
    assert blocked_model.stream_calls == 0
    blocked_preflight = next(
        event for event in blocked_events if event.type == EventType.CONTEXT_PREFLIGHT
    )
    assert (blocked_preflight.payload.status, blocked_preflight.payload.allowed) == (
        "uncertain",
        False,
    )


@pytest.mark.asyncio
async def test_react_requests_recompute_preflight_for_each_final_context():
    class ReactModel(_DescriptorModel):
        def __init__(self):
            super().__init__(_snapshot(headroom=5_000))

        def describe_context_budget(self, messages, tools=None):
            self.describe_calls += 1
            return _snapshot(headroom=5_000 - (self.describe_calls - 1) * 1_000)

        def stream(self, messages, tools=None):
            self.stream_calls += 1
            call = self.stream_calls

            async def iterator():
                if call == 1:
                    yield StreamEvent(
                        type="tool_call",
                        tool_name="echo",
                        tool_id="call-1",
                        arguments={},
                    )
                else:
                    yield StreamEvent(type="content", text="done")

            return iterator()

    class EchoTool:
        name = "echo"
        description = "echo"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, tool_call_id, arguments, **kwargs):
            return "tool result"

    model = ReactModel()
    events = []
    await run_agent_loop(
        AgentContext(),
        AgentLoopConfig(model=model, tools=[EchoTool()]),
        "prompt",
        emit=events.append,
    )

    preflights = [
        event.payload
        for event in events
        if event.type == EventType.CONTEXT_PREFLIGHT
    ]
    assert len(preflights) == 2
    assert [item.snapshot.headroom for item in preflights] == [5_000, 4_000]
    assert model.describe_calls == 2
    assert model.stream_calls == 2
