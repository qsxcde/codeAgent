from __future__ import annotations

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import AgentLoopConfig, EventType
from codeagent.session import AgentSession, EventBus
from codeagent.session.persistence.models import UsageStats
from codeagent.session.store import MemoryStore


def _session(model: ChatModelPort, store: MemoryStore) -> AgentSession:
    return AgentSession(
        AgentLoopConfig(model=model, tools=[]),
        EventBus(),
        store=store,
    )


async def test_session_separates_budget_estimate_actual_and_committed_usage():
    store = MemoryStore()
    session = _session(
        ChatModelPort(
            FakeClient(
                response="ok",
                usage={
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 60},
                },
            ),
            context_window=2_000,
            output_reserve=100,
            reserve_tokens=50,
            window_source="catalog",
        ),
        store,
    )
    events = []
    session.subscribe(events.append)

    await session.run("hello")

    assert session.context_budget is not None
    assert session.context_budget.status == "estimate"
    assert session.context_budget.context_window == 2_000
    assert session.last_actual_usage == UsageStats(
        input_tokens=100,
        output_tokens=20,
        cached_tokens=60,
    )
    assert session.committed_usage == UsageStats(
        input_tokens=100,
        output_tokens=20,
        cached_tokens=60,
    )
    assert session.context_tokens == 100
    assert any(event.type == EventType.CONTEXT_BUDGET for event in events)


async def test_failed_run_does_not_change_committed_usage():
    class BoomClient(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("boom")

    store = MemoryStore()
    session = _session(ChatModelPort(BoomClient(response="no")), store)

    await session.run("fails")

    assert session.committed_usage == UsageStats()
    assert store.load_usage(session.session_id) == UsageStats()


async def test_context_preparation_failure_preserves_budget_diagnostics_and_error_code():
    model = ChatModelPort(
        FakeClient(response="unused"),
        context_window=2_000,
        output_reserve=100,
        reserve_tokens=50,
        window_source="catalog",
    )

    def prepare(_request):
        raise ValueError("context cannot be prepared")

    session = AgentSession(
        AgentLoopConfig(model=model, context_preparer=prepare),
        EventBus(),
        store=MemoryStore(),
    )
    events = []
    session.subscribe(events.append)

    await session.run("fails before model")

    assert session.context_budget is not None
    assert session.context_budget.context_window == 2_000
    error = next(event for event in events if event.type == EventType.ERROR)
    assert error.metadata["error_code"] == "context_preparation_failed"
    assert error.metadata["phase"] == "context_preparation"
    assert error.metadata["retryable"] is False


async def test_session_initial_window_follows_model_metadata_without_override():
    model = ChatModelPort(
        FakeClient(response="ok"),
        context_window=2_000,
        output_reserve=100,
        reserve_tokens=50,
        window_source="catalog",
    )

    session = AgentSession(AgentLoopConfig(model=model), EventBus())

    assert session.context_window == 2_000


async def test_switching_model_window_only_changes_future_budget():
    store = MemoryStore()
    session = _session(
            ChatModelPort(
                FakeClient(response="first"),
                context_window=1_000,
                output_reserve=100,
                reserve_tokens=50,
                window_source="catalog",
        ),
        store,
    )
    await session.run("first")
    history_ids = [message.id for message in session.history]

    session.replace_config(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(response="second"),
                context_window=4_000,
                output_reserve=100,
                reserve_tokens=50,
                window_source="catalog",
            ),
            tools=[],
        )
    )
    await session.run("second")

    assert session.context_budget is not None
    assert session.context_budget.context_window == 4_000
    assert [message.id for message in session.history[:2]] == history_ids
    assert len(store.load_messages(session.session_id)) == 4
