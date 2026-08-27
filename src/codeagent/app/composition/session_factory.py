"""AgentSession 和 SessionManager 的组合根装配。"""

from __future__ import annotations

from typing import Any

from .model_factory import _resolve_context_window, _resolve_model_effort
from .runtime_factory import create_agent_config, policy_for_config, runtime_for_config


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
    approval_mode: str = "deny",
    summarizer: Any = None,
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
    )
    runtime = runtime_for_config(config)
    return AgentSession(
        config,
        EventBus(),
        store=store,
        session_id=session_id,
        recursion_limit=recursion_limit or 50,
        tool_timeout=tool_timeout,
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
    approval_mode: str = "deny",
    summarizer: Any = None,
    context_window: int | None = None,
    config: Any = None,
    mcp_diagnostics: list[str] | None = None,
) -> Any:
    """创建会话管理器并注入共享端口和资源关闭器。"""
    from codeagent.session import SessionManager

    if config is None:
        config = create_agent_config(
            cfg,
            registry=registry,
            reasoning_effort=reasoning_effort,
            provider=provider,
            model=model,
            approval_mode=approval_mode,
            mcp_diagnostics=mcp_diagnostics,
        )
    model_id, effort = _resolve_model_effort(cfg, provider, model, reasoning_effort)

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
        summarizer=summarizer,
        context_window=context_window or _resolve_context_window(
            registry, cfg, provider, model
        ),
        runtime_closer=_close_runtime,
        policy=policy_for_config(config),
    )
