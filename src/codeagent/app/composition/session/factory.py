"""AgentSession 和 SessionManager 的组合根装配。"""

from __future__ import annotations

from typing import Any, Callable

from codeagent.core.context_preflight import ContextPreflightConfig

from ..model.factory import _resolve_context_window, _resolve_model_effort
from ..runtime.factory import create_agent_config, policy_for_config, runtime_for_config


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
    confirmation_timeout: float | None = None,
    approval_mode: str = "deny",
    summarizer: Any = None,
    uncertain_budget_policy: str = "allow",
    context_preflight: ContextPreflightConfig | None = None,
) -> Any:
    """创建有状态的 AgentSession。"""
    from codeagent.session import AgentSession, EventBus

    config = create_agent_config(
        cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
        approval_mode=approval_mode,
        uncertain_budget_policy=uncertain_budget_policy,
        context_preflight=context_preflight,
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
    )


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
    confirmation_timeout: float | None = None,
    approval_mode: str = "deny",
    summarizer: Any = None,
    context_window: int | None = None,
    config: Any = None,
    mcp_diagnostics: list[str] | None = None,
    session_config_factory: Callable[[Any], Any] | None = None,
    uncertain_budget_policy: str = "allow",
    context_preflight: ContextPreflightConfig | None = None,
) -> Any:
    """创建会话管理器并注入共享端口和资源关闭器。"""
    from codeagent.session import SessionManager

    config_was_created = config is None
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
        )
    model_id, effort = _resolve_model_effort(cfg, provider, model, reasoning_effort)

    if session_config_factory is None and config_was_created:
        def _restore_session_config(ref: Any) -> Any:
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
            )

        session_config_factory = _restore_session_config

    async def _close_runtime() -> None:
        runtime = runtime_for_config(config)
        if runtime is not None:
            await runtime.close()

    return SessionManager(
        config,
        store=store,
        model=model_id,
        effort=effort,
        recursion_limit=recursion_limit or 50,
        tool_timeout=tool_timeout,
        confirmation_timeout=confirmation_timeout,
        summarizer=summarizer,
        context_window=context_window or _resolve_context_window(
            registry, cfg, provider, model
        ),
        runtime_closer=_close_runtime,
        policy=policy_for_config(config),
        session_config_factory=session_config_factory,
    )
