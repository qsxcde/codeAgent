"""Single model turn orchestration for the core ReAct loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from codeagent.core.support.awaiting import await_if_needed
from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message, ToolResult
from codeagent.core.model.request import new_model_message
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.core.orchestration.batch import execute_tool_batch
from codeagent.core.orchestration.errors import RecursionLimitError


async def run_turn(
    config: AgentLoopConfig,
    iteration: int,
    is_last: bool,
    emit: Callable[[AgentEvent], Any],
    working: AgentContext,
    new_messages: list[Message],
) -> bool:
    """Run one model request and return whether the outer loop should stop."""
    emit(AgentEvent(EventType.TURN_START, metadata={"turn_index": iteration}))
    assistant = await new_model_message(config, working.messages, emit)
    working.messages.append(assistant)
    new_messages.append(assistant)
    if not assistant.tool_calls:
        emit(AgentEvent(EventType.TURN_END, payload=assistant))
        return True
    if is_last:
        raise RecursionLimitError()
    results = await execute_tool_batch(assistant.tool_calls, working, config, emit)
    _append_tool_messages(working, new_messages, results)
    _append_steering_messages(working, new_messages, config)
    emit(
        AgentEvent(
            EventType.TURN_END,
            payload=assistant,
            metadata={"tool_results": results},
        )
    )
    if config.should_stop_after_turn is None:
        return False
    return bool(await await_if_needed(config.should_stop_after_turn(assistant, results, working)))


def _append_tool_messages(
    working: AgentContext,
    new_messages: list[Message],
    results: list[ToolResult],
) -> None:
    messages = [
        Message(role="tool", content=result.content, tool_call_id=result.tool_call_id)
        for result in results
    ]
    working.messages.extend(messages)
    new_messages.extend(messages)


def _append_steering_messages(
    working: AgentContext,
    new_messages: list[Message],
    config: AgentLoopConfig,
) -> None:
    while config.steer_queue:
        steer = Message(role="user", content=config.steer_queue.pop(0))
        working.messages.append(steer)
        new_messages.append(steer)


__all__ = ["run_turn"]
