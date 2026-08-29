"""Provider-independent context budget values and estimation helpers.

The core layer only knows the neutral shape of a model request.  Composition
roots are responsible for supplying the effective model metadata, system
prompt, and serialized tool definitions.
"""

from __future__ import annotations

import json
import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from codeagent.core.contracts.messages import Message

BudgetStatus = Literal["estimate", "uncertain"]

# Conservative defaults used when an older model adapter cannot describe its
# effective request window.  Keeping these values in core makes the fallback
# explicit without making core depend on the composition root or ai layer.
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_OUTPUT_RESERVE = 4_096
DEFAULT_RESERVE_TOKENS = 16_384


def _validate_non_negative(name: str, value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class ContextBudgetInput:
    """Neutral description of one model request before it is sent."""

    context_window: int
    output_reserve: int = 0
    reserve_tokens: int = 0
    system_prompt: str = ""
    tool_definitions: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    messages: tuple[Message, ...] = field(default_factory=tuple)
    window_source: str = "unknown"

    def __post_init__(self) -> None:
        if type(self.context_window) is not int or self.context_window < 1:
            raise ValueError("context_window must be a positive integer")
        _validate_non_negative("output_reserve", self.output_reserve)
        _validate_non_negative("reserve_tokens", self.reserve_tokens)
        if self.output_reserve + self.reserve_tokens > self.context_window:
            raise ValueError("output_reserve and reserve_tokens exceed context budget")
        if not isinstance(self.system_prompt, str):
            raise ValueError("system_prompt must be a string")
        if not isinstance(self.window_source, str) or not self.window_source:
            raise ValueError("window_source must be a non-empty string")

        object.__setattr__(
            self,
            "tool_definitions",
            tuple(copy.deepcopy(definition) for definition in self.tool_definitions),
        )
        object.__setattr__(
            self,
            "messages",
            tuple(copy.deepcopy(message) for message in self.messages),
        )


@dataclass(frozen=True)
class ContextBudgetSnapshot:
    """Pure result of estimating one model request."""

    context_window: int
    output_reserve: int
    reserve_tokens: int
    input_budget: int
    system_prompt_tokens: int
    tool_definitions_tokens: int
    conversation_tokens: int
    tool_result_tokens: int
    input_tokens: int
    headroom: int
    status: BudgetStatus
    window_source: str


def _estimate_text_tokens(value: str) -> int:
    if not value:
        return 0
    return max(1, len(value) // 4)


def _estimate_message_tokens(message: Message) -> int:
    chars = len(message.content)
    for call in message.tool_calls:
        chars += len(call.name)
        chars += len(json.dumps(call.args, ensure_ascii=False, sort_keys=True))
    return max(1, chars // 4)


def _estimate_tool_definition_tokens(definition: Mapping[str, Any]) -> int:
    serialized = json.dumps(
        dict(definition), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _estimate_text_tokens(serialized)


def estimate_context_budget(request: ContextBudgetInput) -> ContextBudgetSnapshot:
    """Estimate a request without mutating any input message or definition."""

    system_prompt_tokens = _estimate_text_tokens(request.system_prompt)
    tool_definitions_tokens = sum(
        _estimate_tool_definition_tokens(definition)
        for definition in request.tool_definitions
    )
    conversation_tokens = sum(
        _estimate_message_tokens(message)
        for message in request.messages
        if message.role != "tool"
    )
    tool_result_tokens = sum(
        _estimate_message_tokens(message)
        for message in request.messages
        if message.role == "tool"
    )
    input_tokens = (
        system_prompt_tokens
        + tool_definitions_tokens
        + conversation_tokens
        + tool_result_tokens
    )
    input_budget = request.context_window - request.output_reserve - request.reserve_tokens
    status: BudgetStatus = (
        "estimate"
        if request.window_source in {"catalog", "override", "provider"}
        else "uncertain"
    )
    return ContextBudgetSnapshot(
        context_window=request.context_window,
        output_reserve=request.output_reserve,
        reserve_tokens=request.reserve_tokens,
        input_budget=input_budget,
        system_prompt_tokens=system_prompt_tokens,
        tool_definitions_tokens=tool_definitions_tokens,
        conversation_tokens=conversation_tokens,
        tool_result_tokens=tool_result_tokens,
        input_tokens=input_tokens,
        headroom=input_budget - input_tokens,
        status=status,
        window_source=request.window_source,
    )


__all__ = [
    "BudgetStatus",
    "ContextBudgetInput",
    "ContextBudgetSnapshot",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_OUTPUT_RESERVE",
    "DEFAULT_RESERVE_TOKENS",
    "estimate_context_budget",
]
