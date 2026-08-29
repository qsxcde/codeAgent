"""应用组合根使用的运行时扩展集合。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from codeagent.core.context.contracts import (
    AfterToolCall,
    BeforeToolCall,
    ContextBudgetPort,
    ContextPreparer,
    ContextTransformer,
)
from codeagent.core.contracts.hooks import LifecycleHook


@dataclass(frozen=True)
class RuntimeExtensions:
    """由组合根归一并注入 AgentLoopConfig 的扩展端口。"""

    transform_context: ContextTransformer | None = None
    context_preparer: ContextPreparer | None = None
    context_budget: ContextBudgetPort | None = None
    context_transform_timeout: float | None = None
    before_tool_call: BeforeToolCall | None = None
    after_tool_call: AfterToolCall | None = None
    lifecycle_hooks: tuple[LifecycleHook, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lifecycle_hooks", tuple(self.lifecycle_hooks or ()))


def normalize_runtime_extensions(
    extensions: RuntimeExtensions | None,
    lifecycle_hooks: Iterable[LifecycleHook] | None = None,
) -> RuntimeExtensions:
    """归一化新扩展集合和旧 lifecycle_hooks 参数。"""
    if extensions is not None:
        return extensions
    return RuntimeExtensions(lifecycle_hooks=tuple(lifecycle_hooks or ()))


__all__ = ["RuntimeExtensions", "normalize_runtime_extensions"]
