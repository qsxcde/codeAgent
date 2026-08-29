"""Configuration and callback contracts for the in-memory Agent loop."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from codeagent.core.context.budget import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_OUTPUT_RESERVE,
    DEFAULT_RESERVE_TOKENS,
)
from codeagent.core.context.contracts import (
    AfterToolCall,
    BeforeToolCall,
    ContextBudgetPort,
    ContextPreparer,
    TransformContext,
    identity_context,
)
from codeagent.core.context.preflight import ContextPreflightConfig
from codeagent.core.contracts.ports import (
    AgentTool,
    ModelPort,
    ToolExecutionRuntimePort,
)
from codeagent.core.contracts.hooks import LifecycleHook, LifecycleHookEvent

__all__ = ["AgentLoopConfig"]


@dataclass
class AgentLoopConfig:
    """Configuration for the pure in-memory Agent loop."""

    model: ModelPort
    tools: list[AgentTool] = field(default_factory=list)
    transform_context: TransformContext = identity_context
    context_preparer: ContextPreparer | None = None
    context_budget: ContextBudgetPort | None = None
    context_preflight: ContextPreflightConfig = field(
        default_factory=ContextPreflightConfig
    )
    #: Explicit policy for a fallback/uncertain context window. ``allow``
    #: keeps legacy model adapters usable; ``fail`` makes the boundary hard.
    uncertain_budget_policy: str = "allow"
    before_tool_call: BeforeToolCall | None = None
    after_tool_call: AfterToolCall | None = None
    #: Ordered, read-only observers for core lifecycle events.
    lifecycle_hooks: tuple[LifecycleHook, ...] = field(default_factory=tuple)
    tool_execution: str = "parallel"
    tool_timeout: float | None = None
    should_stop_after_turn: Callable[..., Awaitable[bool] | bool] | None = None
    tool_runtime: ToolExecutionRuntimePort | None = None
    #: Runtime-owned steering queue; Agent drains it between tool batches.
    steer_queue: list[str] = field(default_factory=list)
    #: Fallback metadata for model adapters that predate the budget contract.
    context_window: int = DEFAULT_CONTEXT_WINDOW
    output_reserve: int = DEFAULT_OUTPUT_RESERVE
    reserve_tokens: int = DEFAULT_RESERVE_TOKENS
    window_source: str = "fallback"

    def __post_init__(self) -> None:
        self.lifecycle_hooks = tuple(self.lifecycle_hooks or ())
        if self.uncertain_budget_policy not in {"allow", "fail"}:
            raise ValueError("uncertain_budget_policy must be 'allow' or 'fail'")
