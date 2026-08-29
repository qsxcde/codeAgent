from __future__ import annotations

from codeagent.core import (
    AgentLoopConfig,
    ContextBudgetSnapshot,
    ContextPreflightConfig,
    EventType,
    StreamEvent,
)
from codeagent.session import AgentSession, EventBus
from codeagent.session.persistence import MemoryStore


def _snapshot(headroom: int) -> ContextBudgetSnapshot:
    return ContextBudgetSnapshot(
        context_window=12_000,
        output_reserve=1_000,
        reserve_tokens=1_000,
        input_budget=10_000,
        system_prompt_tokens=0,
        tool_definitions_tokens=0,
        conversation_tokens=max(0, 10_000 - headroom),
        tool_result_tokens=0,
        input_tokens=max(0, 10_000 - headroom),
        headroom=headroom,
        status="estimate",
        window_source="catalog",
    )


class _SessionModel:
    model_id = "session-preflight-model"

    def __init__(self, headroom: int) -> None:
        self.headroom = headroom
        self.stream_calls = 0

    def describe_context_budget(self, messages, tools=None):
        return _snapshot(self.headroom)

    def stream(self, messages, tools=None):
        self.stream_calls += 1

        async def iterator():
            yield StreamEvent(type="content", text="ok")

        return iterator()


async def test_session_exposes_latest_preflight_and_resets_it_per_run():
    model = _SessionModel(2_048)
    session = AgentSession(
        AgentLoopConfig(
            model=model,
            context_preflight=ContextPreflightConfig(warning_headroom_tokens=2_048),
        ),
        EventBus(),
        store=MemoryStore(),
    )

    await session.run("first")
    assert session.context_preflight is not None
    assert session.context_preflight.status == "near_limit"

    model.headroom = -1
    events = []
    session.subscribe(events.append)
    await session.run("second")

    assert session.context_preflight is not None
    assert session.context_preflight.status == "over_limit"
    assert model.stream_calls == 1
    error = next(event for event in events if event.type == EventType.ERROR)
    assert error.metadata["error_code"] == "context_budget_exceeded"
    assert error.metadata["retryable"] is False
    assert error.metadata["input_budget"] == 10_000
    assert error.metadata["headroom"] == -1


async def test_preflight_is_runtime_only_and_does_not_change_committed_history():
    store = MemoryStore()
    model = _SessionModel(-1)
    session = AgentSession(
        AgentLoopConfig(model=model),
        EventBus(),
        store=store,
    )

    await session.run("blocked")

    assert session.history == []
    assert session.usage.input_tokens == 0
    assert store.load_messages(session.session_id) == []
    assert store.load_usage(session.session_id).input_tokens == 0
