"""Request-local context transformation helpers."""

from __future__ import annotations

import asyncio
import copy
import inspect
from collections.abc import Callable, Iterable
from typing import Any

from codeagent.core.contracts.errors import ContextTransformTimeoutError
from codeagent.core.contracts.messages import Message, ToolCall
from codeagent.core.support.awaiting import await_if_needed


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


async def invoke_context_extension(
    extension: Callable[[Any], Any],
    value: Any,
    timeout: float | None,
    *,
    extension_name: str,
) -> Any:
    """Run one context extension while preserving cancellation semantics."""
    if timeout is None:
        return await await_if_needed(extension(value))

    deadline = asyncio.timeout(timeout)
    try:
        async with deadline:
            if _is_async_callable(extension):
                result = extension(value)
            else:
                result = await asyncio.to_thread(extension, value)
            return await await_if_needed(result)
    except TimeoutError as exc:
        if deadline.expired():
            raise ContextTransformTimeoutError(extension_name, timeout) from exc
        raise


def materialize_context_messages(
    value: Any,
    *,
    extension: str,
) -> list[Message]:
    """Validate and materialize a context extension's message collection."""
    if value is None or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{extension} must return an iterable of Message")
    try:
        messages = list(value)
    except TypeError as exc:
        raise TypeError(f"{extension} must return an iterable of Message") from exc
    invalid = next(
        (message for message in messages if not isinstance(message, Message)),
        None,
    )
    if invalid is not None:
        raise TypeError(
            f"{extension} returned {type(invalid).__name__}; expected Message"
        )
    return messages


def clone_context_messages(messages: Iterable[Message]) -> list[Message]:
    """Detach every message returned by a context extension."""
    return [clone_message(message) for message in messages]


def _is_async_callable(extension: Callable[..., Any]) -> bool:
    return inspect.iscoroutinefunction(extension) or inspect.iscoroutinefunction(
        getattr(extension, "__call__", None)
    )


__all__ = [
    "clone_context_messages",
    "clone_message",
    "invoke_context_extension",
    "materialize_context_messages",
]
