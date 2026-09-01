"""AgentSession 的组合根装配。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from codeagent.core.context.preflight import ContextPreflightConfig
from codeagent.core.contracts.hooks import LifecycleHook
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.tools.shared import ToolResourceLimits

from ..model.factory import _resolve_context_window
from ..runtime.factory import create_agent_config, runtime_for_config
from ..runtime.extensions import RuntimeExtensions, normalize_runtime_extensions
from ..subagent.factory import make_child_session_factory


def _create_default_subagent_runner(
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
) -> Any:
    from ..subagent.factory import create_serial_subagent_runner

    child_factory = make_child_session_factory(
        create_agent_session,
        cfg=cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
        recursion_limit=recursion_limit,
        tool_timeout=tool_timeout,
        resource_limits=resource_limits,
        confirmation_timeout=confirmation_timeout,
        approval_mode=approval_mode,
        uncertain_budget_policy=uncertain_budget_policy,
        context_preflight=context_preflight,
        extensions=extensions,
        compact_budget=compact_budget,
        compaction_policy=compaction_policy,
    )
    return create_serial_subagent_runner(child_factory)


def create_agent_session(
    cfg: Any = None,
    *,
    registry: Any = None,
    store: Any = None,
    session_id: str | None = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    recursion_limit: int | None = None,
    tool_timeout: float | None = None,
    resource_limits: ToolResourceLimits | None = None,
    confirmation_timeout: float | None = None,
    approval_mode: str = "deny",
    summarizer: Any = None,
    uncertain_budget_policy: str = "allow",
    context_preflight: ContextPreflightConfig | None = None,
    lifecycle_hooks: Iterable[LifecycleHook] | None = None,
    extensions: RuntimeExtensions | None = None,
    compact_budget: int | None = None,
    compaction_policy: CompactionPolicyConfig | None = None,
    enable_subagents: bool = True,
    allowed_tool_names: Iterable[str] | None = None,
    subagent_runner: Any = None,
) -> Any:
    """创建有状态的 AgentSession。"""
    from codeagent.session import AgentSession, EventBus

    runtime_extensions = normalize_runtime_extensions(extensions, lifecycle_hooks)
    if enable_subagents and subagent_runner is None:
        subagent_runner = _create_default_subagent_runner(
            cfg=cfg,
            registry=registry,
            reasoning_effort=reasoning_effort,
            provider=provider,
            model=model,
            recursion_limit=recursion_limit,
            tool_timeout=tool_timeout,
            resource_limits=resource_limits,
            confirmation_timeout=confirmation_timeout,
            approval_mode=approval_mode,
            uncertain_budget_policy=uncertain_budget_policy,
            context_preflight=context_preflight,
            extensions=runtime_extensions,
            compact_budget=compact_budget,
            compaction_policy=compaction_policy,
        )
    subagent_runner = subagent_runner if enable_subagents else None
    config = create_agent_config(
        cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
        approval_mode=approval_mode,
        uncertain_budget_policy=uncertain_budget_policy,
        context_preflight=context_preflight,
        extensions=runtime_extensions,
        resource_limits=resource_limits,
        allowed_tool_names=allowed_tool_names,
        subagent_runner=subagent_runner,
    )
    runtime = runtime_for_config(config)
    return AgentSession(
        config,
        EventBus(),
        store=store,
        session_id=session_id,
        recursion_limit=recursion_limit or 50,
        tool_timeout=tool_timeout,
        confirmation_timeout=confirmation_timeout,
        summarizer=summarizer,
        context_window=_resolve_context_window(registry, cfg, provider, model),
        runtime_closer=runtime.close if runtime is not None else None,
        policy=runtime.policy if runtime is not None else None,
        compact_budget=compact_budget,
        compaction_policy=compaction_policy,
    )


__all__ = ["create_agent_session"]
