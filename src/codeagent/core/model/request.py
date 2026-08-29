"""Prepare a model request and translate its stream into core messages.

This module owns request-local context transformation, budget preflight, and
provider stream normalization. It deliberately knows only core ports and
messages; session persistence and application wiring stay outside ``core``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from collections.abc import Callable
from typing import Any

from codeagent.core.support.awaiting import await_if_needed
from codeagent.core.context.budget import (
    ContextBudgetInput,
    estimate_context_budget,
    govern_tool_messages,
)
from codeagent.core.context.contracts import (
    ContextPreparationRequest,
    ContextToolDefinition,
)
from codeagent.core.context.preflight import evaluate_context_preflight
from codeagent.core.contracts.errors import ContextPreparationError, ContextPreflightError
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message, ToolCall, new_id
from codeagent.core.contracts.ports import AgentTool
from codeagent.core.orchestration.config import AgentLoopConfig


def clone_message(message: Message) -> Message:
    """Clone a message and its mutable tool-call payloads for a request view."""
    return Message(
        role=message.role,
        content=copy.deepcopy(message.content),
        tool_calls=[
            ToolCall(
                id=call.id,
                name=call.name,
                args=copy.deepcopy(call.args),
                details=copy.deepcopy(call.details),
            )
            for call in message.tool_calls
        ],
        tool_call_id=message.tool_call_id,
        id=message.id,
        parent_id=message.parent_id,
        tool_output=copy.deepcopy(message.tool_output),
    )


def neutral_tool_definitions(
    tools: list[AgentTool],
) -> tuple[ContextToolDefinition, ...]:
    """Expose only serializable tool metadata to context extensions."""
    definitions: list[ContextToolDefinition] = []
    for tool in tools:
        name = tool.name
        description = tool.description
        parameters = tool.parameters
        if not isinstance(parameters, Mapping):
            parameters = {"type": "object", "properties": {}}
        definitions.append(
            ContextToolDefinition(
                name=str(name),
                description=str(description),
                parameters=parameters,
            )
        )
    return tuple(definitions)


async def describe_context_budget(
    config: AgentLoopConfig,
    messages: list[Message],
) -> Any:
    """Obtain a budget from the injected provider or core fallback estimator."""
    provider = config.context_budget
    if provider is None:
        provider = getattr(config.model, "describe_context_budget", None)
    if provider is None:
        definitions = neutral_tool_definitions(config.tools)
        return estimate_context_budget(
            ContextBudgetInput(
                context_window=config.context_window,
                output_reserve=config.output_reserve,
                reserve_tokens=config.reserve_tokens,
                tool_definitions=tuple(definition.as_dict() for definition in definitions),
                messages=tuple(clone_message(message) for message in messages),
                window_source=config.window_source,
            )
        )
    describe = getattr(provider, "describe_context_budget", None)
    if describe is None and callable(provider):
        describe = provider
    if describe is None:
        raise TypeError("context budget provider lacks describe_context_budget")
    return await await_if_needed(describe(list(messages), list(config.tools)))


async def prepare_context(
    config: AgentLoopConfig,
    history: list[Message],
    emit: Callable[[AgentEvent], Any],
) -> tuple[list[Message], Any]:
    """Build a temporary model view and publish its final budget snapshot."""
    try:
        source = [clone_message(message) for message in history]
        legacy_view = list(await await_if_needed(config.transform_context(list(source))))
        if config.context_preparer is not None:
            budget = await describe_context_budget(config, legacy_view)
            emit(AgentEvent(EventType.CONTEXT_BUDGET, payload=budget))
            if (
                budget.status == "uncertain"
                and config.uncertain_budget_policy == "fail"
            ):
                result = evaluate_context_preflight(
                    budget,
                    config.context_preflight,
                    uncertain_budget_policy=config.uncertain_budget_policy,
                )
                emit(AgentEvent(EventType.CONTEXT_PREFLIGHT, payload=result))
                raise ContextPreflightError(result)
            prepared = await await_if_needed(
                config.context_preparer(
                    ContextPreparationRequest(
                        messages=tuple(clone_message(message) for message in legacy_view),
                        tools=neutral_tool_definitions(config.tools),
                        budget=budget,
                    )
                )
            )
        else:
            prepared = legacy_view
        transformed = [clone_message(message) for message in prepared]
        final_budget = await describe_context_budget(config, transformed)
        governed = govern_tool_messages(transformed, final_budget)
        if _message_views_differ(transformed, governed):
            transformed = governed
            final_budget = await describe_context_budget(config, transformed)
            emit(AgentEvent(EventType.CONTEXT_BUDGET, payload=final_budget))
        emit(AgentEvent(EventType.CONTEXT_BUDGET, payload=final_budget))
        return transformed, final_budget
    except ContextPreparationError:
        raise
    except Exception as exc:
        raise ContextPreparationError(exc) from exc


async def new_model_message(
    config: AgentLoopConfig,
    history: list[Message],
    emit: Callable[[AgentEvent], Any],
) -> Message:
    """Collect one model stream into a core assistant message."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    emit(AgentEvent(EventType.MESSAGE_START))
    transformed, final_budget = await prepare_context(config, history, emit)
    preflight = evaluate_context_preflight(
        final_budget,
        config.context_preflight,
        uncertain_budget_policy=config.uncertain_budget_policy,
    )
    emit(AgentEvent(EventType.CONTEXT_PREFLIGHT, payload=preflight))
    if not preflight.allowed:
        raise ContextPreflightError(preflight)
    stream = getattr(config.model, "stream_agent", None) or config.model.stream
    async for event in stream(transformed, config.tools):
        if event.type == "content":
            text_parts.append(event.text)
            emit(AgentEvent(EventType.MESSAGE_UPDATE, payload=event.text))
        elif event.type == "thinking":
            emit(
                AgentEvent(
                    EventType.MESSAGE_UPDATE,
                    payload={"type": "thinking_delta", "text": event.text},
                )
            )
        elif event.type == "tool_call":
            index = event.tool_index if event.tool_index is not None else len(tool_calls)
            tool_calls.append(
                ToolCall(
                    id=event.tool_id or new_id(),
                    name=event.tool_name or "",
                    args=dict(event.arguments or {}),
                    details=(
                        {"argument_error": event.argument_error}
                        if event.argument_error
                        else {}
                    ),
                )
            )
            emit(
                AgentEvent(
                    EventType.MESSAGE_UPDATE,
                    payload={
                        "type": "tool_call",
                        "tool_index": index,
                        "tool_name": event.tool_name,
                        "tool_call_id": event.tool_id,
                        "arguments": event.arguments or {},
                    },
                )
            )
        elif event.type == "usage":
            emit(AgentEvent(EventType.USAGE, payload=event.usage or {}))

    message = Message(
        role="assistant",
        content="".join(text_parts),
        tool_calls=tool_calls,
    )
    emit(AgentEvent(EventType.MESSAGE_END, payload=message))
    return message


def _message_views_differ(before: list[Message], after: list[Message]) -> bool:
    return any(
        left.content != right.content or left.tool_output != right.tool_output
        for left, right in zip(before, after)
    )


__all__ = [
    "clone_message",
    "describe_context_budget",
    "neutral_tool_definitions",
    "new_model_message",
    "prepare_context",
]
