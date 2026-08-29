"""Provider-neutral contracts used while preparing model context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.contracts.messages import Message, ToolCall, ToolResult
from codeagent.core.contracts.ports import AgentTool, ToolDecision

__all__ = [
    "AfterToolCall",
    "BeforeToolCall",
    "ContextBudgetPort",
    "ContextPreparationRequest",
    "ContextPreparer",
    "ContextTransformer",
    "ContextToolDefinition",
    "TransformContext",
]


class ContextBudgetPort(Protocol):
    """Optional neutral budget description supplied by the composition root."""

    def describe_context_budget(
        self,
        messages: list[Message],
        tools: list[AgentTool] | None = None,
    ) -> ContextBudgetSnapshot: ...


async def _identity_context(messages: list[Message]) -> list[Message]:
    return list(messages)


class ContextTransformer(Protocol):
    """Provider-neutral transformation applied to one request's messages."""

    def __call__(
        self,
        messages: list[Message],
    ) -> Awaitable[Iterable[Message]] | Iterable[Message]: ...


# Compatibility name retained for callers that use the original contract.
TransformContext = ContextTransformer
ContextPreparer = Callable[
    ["ContextPreparationRequest"], Awaitable[Iterable[Message]] | Iterable[Message]
]
BeforeToolCall = Callable[
    [ToolCall, Any], Awaitable[ToolDecision | None] | ToolDecision | None
]
AfterToolCall = Callable[
    [ToolCall, ToolResult, Any],
    Awaitable[ToolResult | None] | ToolResult | None,
]


@dataclass(frozen=True)
class ContextToolDefinition:
    """Immutable, provider-neutral tool metadata for context extensions."""

    name: str
    description: str = ""
    parameters: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def __post_init__(self) -> None:
        # The outer copy prevents an extension from changing the live tool
        # adapter. Nested schema values are copied too because provider
        # schemas are commonly nested dictionaries/lists.
        import copy

        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "description", str(self.description))
        object.__setattr__(self, "parameters", copy.deepcopy(dict(self.parameters)))

    def as_dict(self) -> dict[str, Any]:
        """Return a detached mapping suitable for pure budget estimation."""
        import copy

        return {
            "name": self.name,
            "description": self.description,
            "parameters": copy.deepcopy(dict(self.parameters)),
        }


@dataclass(frozen=True)
class ContextPreparationRequest:
    """Neutral, per-request view passed to budget-aware extensions."""

    messages: tuple[Message, ...]
    tools: tuple[ContextToolDefinition, ...]
    budget: ContextBudgetSnapshot | None = None


async def identity_context(messages: list[Message]) -> list[Message]:
    """Return a shallow copy for the default context transformation."""
    return list(messages)
