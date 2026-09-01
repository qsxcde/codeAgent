"""Factories for application-layer Subagent runtime components."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from codeagent.core.context.preflight import ContextPreflightConfig
from codeagent.core.contracts.subagents import SubagentRequest
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.tools.shared import ToolResourceLimits

from .runner import ChildSessionFactory, SerialSubagentRunner
from .profiles import allowed_tool_names_for, instructions_for
from ..runtime.extensions import RuntimeExtensions


def create_serial_subagent_runner(
    child_session_factory: ChildSessionFactory,
) -> SerialSubagentRunner:
    """Create the v0.5 serial runner without allocating model resources."""
    return SerialSubagentRunner(child_session_factory)


def make_child_session_factory(
    session_factory: Callable[..., Any],
    *,
    cfg: Any,
    registry: Any,
    reasoning_effort: str | None,
    provider: str | None,
    model: str | None,
    recursion_limit: int | None,
    tool_timeout: float | None,
    resource_limits: ToolResourceLimits | None,
    confirmation_timeout: float | None,
    approval_mode: str,
    uncertain_budget_policy: str,
    context_preflight: ContextPreflightConfig | None,
    extensions: RuntimeExtensions,
    compact_budget: int | None,
    compaction_policy: CompactionPolicyConfig | None,
) -> Callable[[SubagentRequest], Any]:
    """Build a no-recursion, profile-filtered temporary Session factory."""
    def create_child(request: SubagentRequest) -> Any:
        return session_factory(
            cfg,
            registry=registry,
            store=None,
            reasoning_effort=reasoning_effort,
            provider=provider,
            model=model,
            recursion_limit=recursion_limit,
            tool_timeout=tool_timeout,
            resource_limits=resource_limits,
            confirmation_timeout=confirmation_timeout,
            approval_mode=approval_mode,
            summarizer=None,
            uncertain_budget_policy=uncertain_budget_policy,
            context_preflight=context_preflight,
            extensions=extensions,
            compact_budget=compact_budget,
            compaction_policy=compaction_policy,
            enable_subagents=False,
            allowed_tool_names=allowed_tool_names_for(request.profile),
            system_prompt_suffix=instructions_for(request.profile),
        )

    return create_child


__all__ = ["create_serial_subagent_runner", "make_child_session_factory"]
