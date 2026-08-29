from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context.diagnostics import ContextDiagnostics
from codeagent.core.context.preflight import ContextPreflightConfig, evaluate_context_preflight


def _snapshot(*, status: str = "estimate", source: str = "catalog") -> ContextBudgetSnapshot:
    return ContextBudgetSnapshot(
        context_window=16_000,
        output_reserve=1_000,
        reserve_tokens=500,
        input_budget=14_500,
        system_prompt_tokens=100,
        tool_definitions_tokens=200,
        conversation_tokens=3_000,
        tool_result_tokens=700,
        input_tokens=4_000,
        headroom=10_500,
        status=status,  # type: ignore[arg-type]
        window_source=source,
    )


def test_diagnostics_snapshot_exposes_budget_components_and_preflight() -> None:
    snapshot = _snapshot()
    preflight = evaluate_context_preflight(
        snapshot,
        ContextPreflightConfig(warning_headroom_tokens=11_000),
    )

    diagnostics = (
        ContextDiagnostics.from_budget(snapshot, model_id="demo-model")
        .with_preflight(preflight)
        .with_actual_usage(input_tokens=4_100, output_tokens=240, cached_tokens=900)
    )

    assert diagnostics.model_id == "demo-model"
    assert diagnostics.window_certainty == "known"
    assert diagnostics.budget_status == "estimate"
    assert diagnostics.components == {
        "system_prompt": 100,
        "tool_definitions": 200,
        "conversation": 3_000,
        "tool_results": 700,
        "output_reserve": 1_000,
        "reserve": 500,
    }
    assert diagnostics.preflight_status == "near_limit"
    assert diagnostics.actual_input_tokens == 4_100
    assert diagnostics.as_dict()["headroom"] == 10_500


def test_diagnostics_preserves_uncertain_window_without_fake_ratio() -> None:
    diagnostics = ContextDiagnostics.from_budget(
        _snapshot(status="uncertain", source="fallback")
    )

    assert diagnostics.window_certainty == "uncertain"
    assert diagnostics.window_source == "fallback"
    assert diagnostics.usage_percent is None
    assert diagnostics.as_dict()["window"] == {
        "value": 16_000,
        "source": "fallback",
        "certainty": "uncertain",
    }


def test_diagnostics_records_compaction_and_tool_governance_without_mutation() -> None:
    original = ContextDiagnostics.from_budget(_snapshot())
    diagnostics = original.with_compaction(
        trigger="auto",
        status="compacted",
        reason_code="threshold",
        reason="estimated input crossed the threshold",
        before_input_tokens=16_200,
        after_input_tokens=7_800,
        target_tokens=8_000,
        summarized_entry_ids=("m-1", "m-2"),
        kept_entry_ids=("m-3", "m-4"),
    ).with_tool_result(
        tool_call_id="call-1",
        status="ok",
        original_bytes=10_000,
        shown_bytes=2_000,
        action="truncate",
        reason="request_budget",
        facts_complete=True,
    )

    assert original.compaction is None
    assert diagnostics.compaction is not None
    assert diagnostics.compaction.cropped_range == ("m-1", "m-2")
    assert diagnostics.compaction.retained_range == ("m-3", "m-4")
    assert diagnostics.tool_results[0].action == "truncate"
    assert diagnostics.tool_results[0].original_bytes == 10_000
    assert diagnostics.as_dict()["tool_results"][0]["facts_complete"] is True


def test_diagnostics_empty_and_repeat_reads_are_stable() -> None:
    diagnostics = ContextDiagnostics.empty()
    first = diagnostics.as_dict()
    second = diagnostics.as_dict()

    assert first == second
    assert first["budget"] == "unknown"
    assert first["compaction"] == "not_available"
    assert first["tool_results"] == []


def test_diagnostics_failure_does_not_claim_committed_usage() -> None:
    diagnostics = ContextDiagnostics.from_budget(_snapshot()).with_failure(
        code="context_budget_exceeded",
        message="too large",
        phase="context_preflight",
    )

    assert diagnostics.last_failure == {
        "code": "context_budget_exceeded",
        "message": "too large",
        "phase": "context_preflight",
    }
    assert diagnostics.actual_input_tokens is None
