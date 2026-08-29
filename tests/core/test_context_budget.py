from __future__ import annotations

import asyncio
import time
from dataclasses import FrozenInstanceError

import pytest

from codeagent.core.context.budget import (
    ContextBudgetInput,
    estimate_context_budget,
    govern_tool_messages,
)
from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.messages import Message
from codeagent.core.contracts.errors import ContextPreparationError
from codeagent.core.contracts.ports import StreamEvent
from codeagent.core.orchestration.loop import run_agent_loop
from codeagent.core.orchestration.config import AgentLoopConfig


def test_context_transformer_contract_is_explicit_and_compatibly_exported():
    from codeagent.core import ContextTransformer as PublicContextTransformer
    from codeagent.core.context.contracts import ContextTransformer, TransformContext

    assert getattr(ContextTransformer, "_is_protocol", False) is True
    assert TransformContext is ContextTransformer
    assert PublicContextTransformer is ContextTransformer


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_agent_loop_config_rejects_invalid_context_transform_timeout(timeout):
    with pytest.raises(ValueError, match="context_transform_timeout"):
        AgentLoopConfig(model=object(), context_transform_timeout=timeout)


def test_context_budget_rejects_invalid_window_and_reserve_values():
    with pytest.raises(ValueError, match="context_window"):
        ContextBudgetInput(context_window=0)
    with pytest.raises(ValueError, match="output_reserve"):
        ContextBudgetInput(context_window=100, output_reserve=-1)
    with pytest.raises(ValueError, match="budget"):
        ContextBudgetInput(context_window=100, output_reserve=80, reserve_tokens=21)


def test_context_budget_is_immutable_and_reports_all_request_components():
    messages = [
        Message(role="user", content="u" * 80),
        Message(role="tool", content="result" * 80, tool_call_id="call-1"),
    ]
    original_messages = list(messages)
    request = ContextBudgetInput(
        context_window=2_000,
        output_reserve=300,
        reserve_tokens=100,
        system_prompt="system prompt" * 10,
        tool_definitions=(
            {
                "name": "search",
                "description": "search the workspace",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        ),
        messages=messages,
        window_source="catalog",
    )

    snapshot = estimate_context_budget(request)

    assert snapshot.system_prompt_tokens > 0
    assert snapshot.tool_definitions_tokens > 0
    assert snapshot.conversation_tokens > 0
    assert snapshot.tool_result_tokens > 0
    assert snapshot.input_tokens == (
        snapshot.system_prompt_tokens
        + snapshot.tool_definitions_tokens
        + snapshot.conversation_tokens
        + snapshot.tool_result_tokens
    )
    assert snapshot.input_budget == 1_600
    assert snapshot.headroom == snapshot.input_budget - snapshot.input_tokens
    assert snapshot.status == "estimate"
    assert messages == original_messages

    with pytest.raises(FrozenInstanceError):
        request.context_window = 1  # type: ignore[misc]


def test_context_budget_has_zero_tool_definition_cost_without_tools():
    snapshot = estimate_context_budget(
        ContextBudgetInput(
            context_window=1_000,
            system_prompt="system",
            messages=[Message(role="user", content="hello")],
        )
    )

    assert snapshot.tool_definitions_tokens == 0
    assert snapshot.input_tokens == (
        snapshot.system_prompt_tokens + snapshot.conversation_tokens
    )


def test_context_budget_repeated_estimation_is_stable():
    request = ContextBudgetInput(
        context_window=1_000,
        output_reserve=100,
        reserve_tokens=50,
        system_prompt="system",
        messages=(Message(role="user", content="hello"),),
        window_source="catalog",
    )

    assert estimate_context_budget(request) == estimate_context_budget(request)


def test_context_budget_detaches_mutable_input_values():
    message = Message(role="user", content="before")
    definition = {"name": "search", "parameters": {"properties": {}}}
    request = ContextBudgetInput(
        context_window=1_000,
        messages=(message,),
        tool_definitions=(definition,),
        window_source="catalog",
    )
    before = estimate_context_budget(request)

    message.content = "after" * 100
    definition["parameters"]["properties"]["q"] = {"type": "string"}

    assert estimate_context_budget(request) == before


def test_govern_tool_messages_crops_to_request_headroom_and_keeps_facts():
    from codeagent.core.contracts.messages import OutputCompleteness, ToolOutputMetadata

    metadata = ToolOutputMetadata(
        completeness=OutputCompleteness.COMPLETE,
        total_bytes=1_000,
        total_lines=100,
        shown_bytes=1_000,
        shown_lines=100,
        path="README.md",
    )
    messages = [
        Message(role="user", content="u" * 120),
        Message(
            role="tool",
            content="x" * 400,
            tool_call_id="call-1",
            tool_output=metadata,
        ),
    ]
    budget = estimate_context_budget(
        ContextBudgetInput(
            context_window=100,
            output_reserve=10,
            reserve_tokens=10,
            messages=tuple(messages),
            window_source="catalog",
        )
    )

    governed = govern_tool_messages(messages, budget)

    assert len(governed) == 2
    result = governed[1]
    assert len(result.content) < len(messages[1].content)
    assert result.tool_output is not None
    assert result.tool_output.truncated_by == "request_budget"
    assert result.tool_output.completeness == OutputCompleteness.TRUNCATED
    assert result.tool_output.total_bytes == 1_000
    assert "README.md" in result.content
    assert messages[1].content == "x" * 400


def test_govern_tool_messages_marks_legacy_result_unknown_when_cropped():
    messages = [Message(role="tool", content="x" * 400, tool_call_id="call-1")]
    budget = estimate_context_budget(
        ContextBudgetInput(
            context_window=20,
            output_reserve=10,
            messages=tuple(messages),
            window_source="unknown",
        )
    )

    result = govern_tool_messages(messages, budget)[0]

    assert result.tool_output is not None
    assert result.tool_output.source == "budget"
    assert result.tool_output.completeness == "truncated"


def test_govern_tool_messages_keeps_multiple_call_id_facts_independent():
    from codeagent.core.contracts.messages import OutputCompleteness, ToolOutputMetadata

    first = Message(
        role="tool",
        content="a" * 240,
        tool_call_id="call-a",
        tool_output=ToolOutputMetadata(
            completeness=OutputCompleteness.COMPLETE,
            total_bytes=240,
            total_lines=1,
            shown_bytes=240,
            shown_lines=1,
            path="a.py",
        ),
    )
    second = Message(
        role="tool",
        content="b" * 240,
        tool_call_id="call-b",
        tool_output=ToolOutputMetadata(
            completeness=OutputCompleteness.COMPLETE,
            total_bytes=240,
            total_lines=1,
            shown_bytes=240,
            shown_lines=1,
            path="b.py",
        ),
    )
    budget = estimate_context_budget(
        ContextBudgetInput(
            context_window=80,
            output_reserve=10,
            messages=(first, second),
            window_source="catalog",
        )
    )

    governed = govern_tool_messages([first, second], budget)

    assert [message.tool_call_id for message in governed] == ["call-a", "call-b"]
    assert governed[0].tool_output.path == "a.py"
    assert governed[1].tool_output.path == "b.py"
    assert all(message.tool_output.truncated_by == "request_budget" for message in governed)


class _BudgetAwareModel:
    model_id = "test-model"

    def __init__(self) -> None:
        self.received: list[Message] = []

    def describe_context_budget(self, messages, tools=None):
        return estimate_context_budget(
            ContextBudgetInput(
                context_window=2_000,
                output_reserve=100,
                messages=tuple(messages),
                window_source="catalog",
            )
        )

    def stream(self, messages, tools=None):
        self.received = list(messages)

        async def events():
            yield StreamEvent(type="content", text="ok")

        return events()


@pytest.mark.asyncio
async def test_budget_aware_context_preparer_gets_neutral_view_and_keeps_source_context():
    from codeagent.core.context.contracts import ContextPreparationRequest

    model = _BudgetAwareModel()
    source = AgentContext(messages=[Message(role="user", content="history")])
    seen: list[ContextPreparationRequest] = []

    def prepare(request: ContextPreparationRequest):
        seen.append(request)
        return [*request.messages, Message(role="user", content="temporary")]

    await run_agent_loop(
        source,
        AgentLoopConfig(model=model, context_preparer=prepare),
        "prompt",
    )

    assert len(seen) == 1
    assert seen[0].budget is not None
    assert seen[0].budget.status == "estimate"
    assert [message.content for message in seen[0].messages] == [
        "history",
        "prompt",
    ]
    assert [message.content for message in model.received] == [
        "history",
        "prompt",
        "temporary",
    ]
    assert [message.content for message in source.messages] == ["history"]


@pytest.mark.asyncio
async def test_context_hooks_compose_and_isolate_source_messages():
    model = _BudgetAwareModel()
    source = AgentContext(messages=[Message(role="user", content="history")])
    calls: list[str] = []

    def legacy_transform(messages):
        calls.append("legacy")
        messages[0].content = "legacy-view"
        return messages

    def prepare(request):
        calls.append("budget-aware")
        request.messages[0].content = "budget-view"
        return list(request.messages)

    await run_agent_loop(
        source,
        AgentLoopConfig(
            model=model,
            transform_context=legacy_transform,
            context_preparer=prepare,
        ),
        "prompt",
    )

    assert calls == ["legacy", "budget-aware"]
    assert source.messages[0].content == "history"
    assert model.received[0].content == "budget-view"


@pytest.mark.asyncio
async def test_context_preparer_receives_neutral_tool_definitions():
    class Tool:
        name = "search"
        description = "search workspace"
        parameters = {"type": "object", "properties": {}}

    model = _BudgetAwareModel()
    seen: list = []

    def prepare(request):
        seen.append(request)
        return list(request.messages)

    await run_agent_loop(
        AgentContext(),
        AgentLoopConfig(model=model, tools=[Tool()], context_preparer=prepare),
        "prompt",
    )

    assert len(seen[0].tools) == 1
    from codeagent.core.context.contracts import ContextToolDefinition

    assert isinstance(seen[0].tools[0], ContextToolDefinition)
    assert seen[0].tools[0].name == "search"
    assert seen[0].tools[0].parameters == {
        "type": "object",
        "properties": {},
    }


@pytest.mark.asyncio
async def test_model_without_budget_descriptor_emits_uncertain_snapshot():
    class LegacyModel:
        model_id = "legacy-model"

        def stream(self, messages, tools=None):
            async def events():
                yield StreamEvent(type="content", text="ok")

            return events()

    events = []
    await run_agent_loop(
        AgentContext(),
        AgentLoopConfig(model=LegacyModel()),
        "prompt",
        emit=events.append,
    )

    budget = next(event.payload for event in events if event.type == "context_budget")
    assert budget.status == "uncertain"
    assert budget.window_source == "fallback"


@pytest.mark.asyncio
async def test_uncertain_budget_policy_can_fail_before_extension_runs():
    class LegacyModel:
        model_id = "legacy-model"

        def stream(self, messages, tools=None):  # pragma: no cover - must not run
            raise AssertionError("model stream must not run")

    called = False

    def prepare(_request):
        nonlocal called
        called = True
        return []

    events = []
    with pytest.raises(ContextPreparationError, match="context window is uncertain"):
        await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(
                model=LegacyModel(),
                context_preparer=prepare,
                uncertain_budget_policy="fail",
            ),
            "prompt",
            emit=events.append,
        )

    assert called is False
    budget = next(event.payload for event in events if event.type == "context_budget")
    assert budget.status == "uncertain"
    preflight = next(event.payload for event in events if event.type == "context_preflight")
    assert (preflight.status, preflight.allowed) == ("uncertain", False)


@pytest.mark.asyncio
async def test_legacy_transform_context_remains_supported():
    model = _BudgetAwareModel()
    seen: list[str] = []

    def transform(messages):
        seen.extend(message.content for message in messages)
        return list(messages)

    await run_agent_loop(
        AgentContext(),
        AgentLoopConfig(model=model, transform_context=transform),
        "legacy",
    )

    assert seen == ["legacy"]


@pytest.mark.parametrize("invalid_result", [None, ["not-a-message"]])
@pytest.mark.asyncio
async def test_context_transformer_rejects_invalid_results_without_model_fallback(
    invalid_result,
):
    model = _BudgetAwareModel()
    source = AgentContext(messages=[Message(role="user", content="history")])
    events = []

    def transform(_messages):
        return invalid_result

    with pytest.raises(ContextPreparationError) as raised:
        await run_agent_loop(
            source,
            AgentLoopConfig(model=model, transform_context=transform),
            "prompt",
            emit=events.append,
        )

    assert raised.value.code == "context_preparation_failed"
    assert model.received == []
    assert [message.content for message in source.messages] == ["history"]
    error = next(event for event in events if event.type == "error")
    assert error.metadata["error_code"] == "context_preparation_failed"


@pytest.mark.asyncio
async def test_context_transformer_timeout_blocks_model_and_preserves_history():
    model = _BudgetAwareModel()
    source = AgentContext(messages=[Message(role="user", content="history")])
    events = []

    async def transform(_messages):
        await asyncio.sleep(10)
        return []

    with pytest.raises(ContextPreparationError) as raised:
        await run_agent_loop(
            source,
            AgentLoopConfig(
                model=model,
                transform_context=transform,
                context_transform_timeout=0.01,
            ),
            "prompt",
            emit=events.append,
        )

    assert raised.value.code == "context_transform_timeout"
    assert raised.value.extension == "transform_context"
    assert raised.value.timeout == 0.01
    assert model.received == []
    assert [message.content for message in source.messages] == ["history"]
    error = next(event for event in events if event.type == "error")
    assert error.metadata["error_code"] == "context_transform_timeout"
    assert error.metadata["extension"] == "transform_context"


@pytest.mark.asyncio
async def test_context_preparer_timeout_uses_same_contract():
    model = _BudgetAwareModel()
    events = []

    async def prepare(_request):
        await asyncio.sleep(10)
        return []

    with pytest.raises(ContextPreparationError) as raised:
        await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(
                model=model,
                context_preparer=prepare,
                context_transform_timeout=0.01,
            ),
            "prompt",
            emit=events.append,
        )

    assert raised.value.code == "context_transform_timeout"
    assert raised.value.extension == "context_preparer"
    assert model.received == []
    assert next(event for event in events if event.type == "error").metadata[
        "extension"
    ] == "context_preparer"


@pytest.mark.asyncio
async def test_context_preparer_rejects_invalid_result_without_model_call():
    model = _BudgetAwareModel()
    source = AgentContext(messages=[Message(role="user", content="history")])

    def prepare(_request):
        return ["not-a-message"]

    with pytest.raises(ContextPreparationError) as raised:
        await run_agent_loop(
            source,
            AgentLoopConfig(model=model, context_preparer=prepare),
            "prompt",
        )

    assert raised.value.code == "context_preparation_failed"
    assert model.received == []
    assert [message.content for message in source.messages] == ["history"]


@pytest.mark.asyncio
async def test_context_transformer_cancellation_is_not_wrapped():
    model = _BudgetAwareModel()
    started = asyncio.Event()
    cancelled = False

    async def transform(_messages):
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True

    task = asyncio.create_task(
        run_agent_loop(
            AgentContext(),
            AgentLoopConfig(
                model=model,
                transform_context=transform,
                context_transform_timeout=1,
            ),
            "prompt",
        )
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled is True
    assert model.received == []


@pytest.mark.asyncio
async def test_sync_context_transformer_timeout_bounds_waiting():
    model = _BudgetAwareModel()
    started = time.monotonic()

    def transform(messages):
        time.sleep(0.15)
        return messages

    with pytest.raises(ContextPreparationError) as raised:
        await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(
                model=model,
                transform_context=transform,
                context_transform_timeout=0.01,
            ),
            "prompt",
        )

    assert raised.value.code == "context_transform_timeout"
    assert time.monotonic() - started < 0.1
    assert model.received == []


class _BrokenBudgetModel:
    model_id = "broken-budget"

    def describe_context_budget(self, messages, tools=None):
        raise ValueError("window metadata unavailable")

    def stream(self, messages, tools=None):  # pragma: no cover - must not run
        raise AssertionError("model stream must not run after budget failure")


@pytest.mark.asyncio
async def test_budget_failure_emits_a_staged_runtime_error():
    events = []

    with pytest.raises(ValueError, match="window metadata unavailable"):
        await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(model=_BrokenBudgetModel()),
            "prompt",
            emit=events.append,
        )

    error = next(event for event in events if event.type == "error")
    assert error.metadata["error_code"] == "context_preparation_failed"
    assert error.metadata["phase"] == "context_preparation"
    assert error.metadata["cause_type"] == "ValueError"
