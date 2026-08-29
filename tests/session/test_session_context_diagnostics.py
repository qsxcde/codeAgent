from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import AgentLoopConfig
from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context.preflight import ContextPreflightConfig, evaluate_context_preflight
from codeagent.session import AgentSession, EventBus
from codeagent.session.persistence import MemoryStore
from codeagent.session.runtime.state import SessionBudgetState


def _snapshot() -> ContextBudgetSnapshot:
    return ContextBudgetSnapshot(
        context_window=10_000,
        output_reserve=500,
        reserve_tokens=500,
        input_budget=9_000,
        system_prompt_tokens=100,
        tool_definitions_tokens=200,
        conversation_tokens=1_000,
        tool_result_tokens=300,
        input_tokens=1_600,
        headroom=7_400,
        status="estimate",
        window_source="catalog",
    )


def test_session_budget_state_merges_runtime_diagnostics_without_losing_estimate() -> None:
    state = SessionBudgetState()
    snapshot = _snapshot()
    state.record_estimate(snapshot, model_id="demo")
    state.record_preflight(
        evaluate_context_preflight(
            snapshot,
            ContextPreflightConfig(warning_headroom_tokens=8_000),
        )
    )
    state.record_actual_usage(
        {"input_tokens": 1_700, "output_tokens": 80, "cached_tokens": 400}
    )
    state.record_compaction(
        {
            "trigger": "auto",
            "status": "compacted",
            "reason_code": "threshold",
            "reason": "threshold reached",
            "before_input_tokens": 9_100,
            "after_input_tokens": 4_000,
            "target_budget": 5_000,
            "summarized_entry_ids": ["m-1", "m-2"],
            "kept_entry_ids": ["m-3", "m-4"],
        }
    )
    state.record_tool_result(
        {
            "tool_call_id": "call-1",
            "status": "ok",
            "output_metadata": {
                "total_bytes": 10_000,
                "shown_bytes": 2_000,
                "truncated_by": "request_budget",
                "semantic_success": True,
            },
        }
    )

    diagnostics = state.diagnostics
    assert diagnostics.input_tokens == 1_600
    assert diagnostics.actual_input_tokens == 1_700
    assert diagnostics.preflight_status == "near_limit"
    assert diagnostics.compaction is not None
    assert diagnostics.compaction.cropped_range == ("m-1", "m-2")
    assert diagnostics.tool_results[0].action == "request_budget"


def test_session_budget_state_diagnostic_failure_clears_uncommitted_actual_usage() -> None:
    state = SessionBudgetState()
    state.record_estimate(_snapshot(), model_id="demo")
    state.record_actual_usage({"input_tokens": 1_700})
    state.record_failure(
        {
            "error_code": "context_budget_exceeded",
            "error_message": "too large",
            "phase": "context_preflight",
        }
    )

    assert state.diagnostics.actual_input_tokens is None
    assert state.diagnostics.last_failure == {
        "code": "context_budget_exceeded",
        "message": "too large",
        "phase": "context_preflight",
    }


async def test_agent_session_exposes_latest_context_diagnostics_after_request() -> None:
    session = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(
                    response="ok",
                    usage={"input_tokens": 80, "output_tokens": 20},
                ),
                context_window=2_000,
                output_reserve=100,
                reserve_tokens=50,
                window_source="catalog",
            )
        ),
        EventBus(),
        store=MemoryStore(),
    )

    await session.run("hello")

    diagnostics = session.context_diagnostics
    assert diagnostics.model_id
    assert diagnostics.input_tokens is not None
    assert diagnostics.preflight_status == "near_limit"
    assert diagnostics.actual_input_tokens == 80


async def test_agent_session_marks_uncertain_window_without_fake_percentage() -> None:
    session = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(
                    response="ok",
                    usage={"input_tokens": 80, "output_tokens": 20},
                ),
                context_window=2_000,
                window_source="uncertain",
            )
        ),
        EventBus(),
        store=MemoryStore(),
    )

    await session.run("hello")

    diagnostics = session.context_diagnostics
    assert diagnostics.window_certainty == "uncertain"
    assert diagnostics.usage_percent is None


def test_model_switch_clears_stale_budget_until_next_request() -> None:
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import ChatModelPort

    session = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(response="ok", model="old-model"),
                context_window=2_000,
                window_source="catalog",
            )
        ),
        EventBus(),
        store=MemoryStore(),
    )
    session._budget_state.record_estimate(_snapshot(), model_id="old-model")

    session.replace_config(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(response="ok", model="new-model"),
                context_window=4_000,
                window_source="catalog",
            )
        )
    )

    assert session.context_diagnostics.model_id == "new-model"
    assert session.context_diagnostics.input_tokens is None


def test_context_diagnostics_read_does_not_mutate_session_or_store() -> None:
    store = MemoryStore()
    session = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(response="ok"),
                context_window=4_000,
                window_source="catalog",
            )
        ),
        EventBus(),
        store=store,
    )
    session._budget_state.record_estimate(_snapshot(), model_id="demo")
    history_before = session.history
    refs_before = store.list()
    usage_before = session.usage
    persisted_before = session.is_persisted

    first = session.context_diagnostics.as_dict()
    second = session.context_diagnostics.as_dict()

    assert first == second
    assert session.history == history_before
    assert store.list() == refs_before
    assert session.usage == usage_before
    assert session.is_persisted is persisted_before
