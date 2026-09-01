"""SessionManager 的组合根装配。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from codeagent.core.context.preflight import ContextPreflightConfig
from codeagent.core.contracts.hooks import LifecycleHook
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.tools.shared import ToolResourceLimits

from ..model.factory import _resolve_context_window, _resolve_model_effort
from ..runtime.factory import (
    close_runtime_for_config_async,
    create_agent_config,
    policy_for_config,
)
from ..runtime.extensions import RuntimeExtensions, normalize_runtime_extensions
from ..subagent.factory import make_child_session_factory
from .agent_factory import create_agent_session


def _manager_hooks(
    extensions: RuntimeExtensions | None,
    lifecycle_hooks: Iterable[LifecycleHook] | None,
    normalized: RuntimeExtensions,
) -> tuple[LifecycleHook, ...] | None:
    """保持显式组合对象或旧 Hook 参数对 manager 的覆盖语义。"""
    if extensions is not None or lifecycle_hooks is not None:
        return normalized.lifecycle_hooks
    return None


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


def _make_restore_session_config(
    cfg: Any,
    registry: Any,
    reasoning_effort: str | None,
    provider: str | None,
    model: str | None,
    approval_mode: str,
    mcp_diagnostics: list[str] | None,
    uncertain_budget_policy: str,
    context_preflight: ContextPreflightConfig | None,
    extensions: RuntimeExtensions,
    resource_limits: ToolResourceLimits | None,
    subagent_runner: Any,
) -> Callable[[Any], AgentLoopConfig]:
    """创建携带不可变扩展集合的 session 恢复配置工厂。"""

    def restore(ref: Any) -> AgentLoopConfig:
        return create_agent_config(
            cfg,
            registry=registry,
            reasoning_effort=ref.effort or reasoning_effort,
            provider=provider,
            model=ref.model or model,
            approval_mode=approval_mode,
            mcp_diagnostics=mcp_diagnostics,
            uncertain_budget_policy=uncertain_budget_policy,
            context_preflight=context_preflight,
            extensions=extensions,
            resource_limits=resource_limits,
            subagent_runner=subagent_runner,
        )

    return restore


def create_session_manager(
    cfg: Any = None,
    *,
    registry: Any = None,
    store: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    recursion_limit: int | None = None,
    tool_timeout: float | None = None,
    resource_limits: ToolResourceLimits | None = None,
    confirmation_timeout: float | None = None,
    approval_mode: str = "deny",
    summarizer: Any = None,
    context_window: int | None = None,
    config: Any = None,
    mcp_diagnostics: list[str] | None = None,
    session_config_factory: Callable[[Any], Any] | None = None,
    uncertain_budget_policy: str = "allow",
    context_preflight: ContextPreflightConfig | None = None,
    lifecycle_hooks: Iterable[LifecycleHook] | None = None,
    extensions: RuntimeExtensions | None = None,
    compact_budget: int | None = None,
    compaction_policy: CompactionPolicyConfig | None = None,
    enable_subagents: bool = True,
    subagent_runner: Any = None,
) -> Any:
    """创建会话管理器并注入共享端口和资源关闭器。"""
    from codeagent.session import SessionManager

    (
        config,
        model_id,
        effort,
        session_config_factory,
        manager_hooks,
    ) = _prepare_manager(
        cfg=cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
        approval_mode=approval_mode,
        mcp_diagnostics=mcp_diagnostics,
        config=config,
        session_config_factory=session_config_factory,
        uncertain_budget_policy=uncertain_budget_policy,
        context_preflight=context_preflight,
        lifecycle_hooks=lifecycle_hooks,
        extensions=extensions,
        resource_limits=resource_limits,
        recursion_limit=recursion_limit,
        tool_timeout=tool_timeout,
        confirmation_timeout=confirmation_timeout,
        compact_budget=compact_budget,
        compaction_policy=compaction_policy,
        enable_subagents=enable_subagents,
        subagent_runner=subagent_runner,
    )
    return SessionManager(
        config,
        store=store,
        model=model_id,
        effort=effort,
        recursion_limit=recursion_limit or 50,
        tool_timeout=tool_timeout,
        confirmation_timeout=confirmation_timeout,
        summarizer=summarizer,
        context_window=context_window or _resolve_context_window(registry, cfg, provider, model),
        runtime_closer=lambda: close_runtime_for_config_async(config),
        policy=policy_for_config(config),
        session_config_factory=session_config_factory,
        lifecycle_hooks=manager_hooks,
        compact_budget=compact_budget,
        compaction_policy=compaction_policy,
    )


def _prepare_manager(
    *,
    cfg: Any,
    registry: Any,
    reasoning_effort: str | None,
    provider: str | None,
    model: str | None,
    approval_mode: str,
    mcp_diagnostics: list[str] | None,
    config: Any,
    session_config_factory: Callable[[Any], Any] | None,
    uncertain_budget_policy: str,
    context_preflight: ContextPreflightConfig | None,
    lifecycle_hooks: Iterable[LifecycleHook] | None,
    extensions: RuntimeExtensions | None,
    resource_limits: ToolResourceLimits | None,
    recursion_limit: int | None,
    tool_timeout: float | None,
    confirmation_timeout: float | None,
    compact_budget: int | None,
    compaction_policy: CompactionPolicyConfig | None,
    enable_subagents: bool,
    subagent_runner: Any,
) -> tuple[Any, str, str, Callable[[Any], Any] | None, tuple[LifecycleHook, ...] | None]:
    runtime_extensions = normalize_runtime_extensions(extensions, lifecycle_hooks)
    manager_hooks = _manager_hooks(extensions, lifecycle_hooks, runtime_extensions)
    config_was_created = config is None
    if enable_subagents and subagent_runner is None and config_was_created:
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
    if config_was_created:
        config = create_agent_config(
            cfg,
            registry=registry,
            reasoning_effort=reasoning_effort,
            provider=provider,
            model=model,
            approval_mode=approval_mode,
            mcp_diagnostics=mcp_diagnostics,
            uncertain_budget_policy=uncertain_budget_policy,
            context_preflight=context_preflight,
            extensions=runtime_extensions,
            resource_limits=resource_limits,
            subagent_runner=subagent_runner,
        )
    model_id, effort = _resolve_model_effort(cfg, provider, model, reasoning_effort)
    if session_config_factory is None and config_was_created:
        session_config_factory = _make_restore_session_config(
            cfg,
            registry,
            reasoning_effort,
            provider,
            model,
            approval_mode,
            mcp_diagnostics,
            uncertain_budget_policy,
            context_preflight,
            runtime_extensions,
            resource_limits,
            subagent_runner,
        )
    return config, model_id, effort, session_config_factory, manager_hooks


__all__ = ["create_session_manager"]
