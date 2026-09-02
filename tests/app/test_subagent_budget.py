"""V5-04 budget policy and delegate boundary tests."""

from __future__ import annotations

import asyncio

import pytest

from codeagent.core.contracts.subagents import (
    SubagentBudget,
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
)


class _RecordingRunner:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request, *, on_event=None) -> SubagentResult:
        del on_event
        self.requests.append(request)
        return SubagentResult(
            delegation_id=request.delegation_id,
            status=SubagentStatus.COMPLETED,
            summary="ok",
        )

    async def cancel(self, delegation_id: str) -> bool:
        del delegation_id
        return False


@pytest.mark.unit
def test_effective_budget_uses_defaults_and_rejects_hard_limit_overflow() -> None:
    from codeagent.app.composition.subagent.budget import (
        DEFAULT_MAX_TOOL_CALLS,
        DEFAULT_MAX_TURNS,
        DEFAULT_MAX_OUTPUT_CHARS,
        DEFAULT_TIMEOUT_SECONDS,
        effective_budget,
    )

    defaults = effective_budget(SubagentBudget())
    assert defaults.max_turns == DEFAULT_MAX_TURNS == 8
    assert defaults.max_tool_calls == DEFAULT_MAX_TOOL_CALLS == 32
    assert defaults.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 120.0
    assert defaults.max_output_chars == DEFAULT_MAX_OUTPUT_CHARS == 8_000

    with pytest.raises(ValueError, match="max_turns"):
        effective_budget(SubagentBudget(max_turns=17))
    with pytest.raises(ValueError, match="timeout_seconds"):
        effective_budget(SubagentBudget(timeout_seconds=301.0))


@pytest.mark.unit
async def test_delegate_maps_budget_and_rejects_malformed_budget() -> None:
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    runner = _RecordingRunner()
    tool = DelegateTool(runner).bind_parent_run_id("parent-run")

    result = await tool.execute(
        "call-1",
        {
            "task": "inspect files",
            "budget": {
                "max_turns": 3,
                "max_tool_calls": 7,
                "timeout_seconds": 12.5,
                "max_output_chars": 900,
            },
        },
    )

    assert result.error is False
    assert runner.requests[0].budget == SubagentBudget(
        max_turns=3,
        max_tool_calls=7,
        timeout_seconds=12.5,
        max_output_chars=900,
    )

    malformed = await tool.execute(
        "call-2",
        {"task": "inspect", "budget": {"unknown": 1}},
    )
    oversized = await tool.execute(
        "call-3",
        {"task": "inspect", "budget": {"max_tool_calls": 65}},
    )
    null_field = await tool.execute(
        "call-4",
        {"task": "inspect", "budget": {"max_turns": None}},
    )

    assert malformed.error is True
    assert malformed.details["reason_code"] == "invalid_request"
    assert oversized.error is True
    assert oversized.details["reason_code"] in {"invalid_request", "budget_exceeded"}
    assert null_field.error is True
    assert null_field.details["reason_code"] == "invalid_request"
    assert len(runner.requests) == 1


@pytest.mark.unit
async def test_delegate_enforces_four_accepted_children_per_parent_run() -> None:
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    runner = _RecordingRunner()
    tool = DelegateTool(runner).bind_parent_run_id("parent-run")

    results = await asyncio.gather(
        *[
            tool.execute(f"call-{index}", {"task": f"inspect {index}"})
            for index in range(5)
        ]
    )

    assert [result.error for result in results[:4]] == [False] * 4
    assert results[4].error is True
    assert results[4].details["reason_code"] == "budget_exceeded"
    assert len(runner.requests) == 4


@pytest.mark.integration
@pytest.mark.parametrize("profile", ("explore", "review"))
def test_child_factory_applies_profile_policy_and_effective_max_turns(profile: str) -> None:
    from codeagent.app.composition.runtime.extensions import RuntimeExtensions
    from codeagent.app.composition.subagent.factory import make_child_session_factory
    from codeagent.app.composition.subagent.profiles import (
        READ_ONLY_TOOL_NAMES,
        prompt_for,
    )

    captured = {}

    def session_factory(*args, **kwargs):
        del args
        captured.update(kwargs)
        return object()

    factory = make_child_session_factory(
        session_factory,
        cfg=None,
        registry=None,
        reasoning_effort=None,
        provider=None,
        model=None,
        recursion_limit=50,
        tool_timeout=None,
        resource_limits=None,
        confirmation_timeout=None,
        approval_mode="deny",
        uncertain_budget_policy="allow",
        context_preflight=None,
        extensions=RuntimeExtensions(),
        compact_budget=None,
        compaction_policy=None,
    )

    factory(
        SubagentRequest(
            delegation_id="delegation-factory",
            parent_run_id="parent-run",
            task="inspect",
            profile=profile,
            budget=SubagentBudget(max_turns=3),
        )
    )

    assert captured["recursion_limit"] == 3
    assert captured["enable_subagents"] is False
    assert captured["store"] is None
    assert captured["allowed_tool_names"] == READ_ONLY_TOOL_NAMES
    assert captured["system_prompt_suffix"] == prompt_for(profile)


@pytest.mark.unit
def test_delegate_schema_exposes_bounded_budget_fields() -> None:
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    budget = DelegateTool.parameters["properties"]["budget"]
    assert budget["additionalProperties"] is False
    assert budget["properties"]["max_turns"]["maximum"] == 16
    assert budget["properties"]["max_tool_calls"]["maximum"] == 64
    assert budget["properties"]["timeout_seconds"]["maximum"] == 300
    assert budget["properties"]["max_output_chars"]["maximum"] == 16_000
