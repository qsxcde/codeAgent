"""模型、工具和策略端口的运行时资源所有权与装配。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterable
from typing import Any, Callable

from codeagent.core.context.contracts import identity_context
from codeagent.core.contracts.hooks import LifecycleHook
from codeagent.core.execution.runtime import ToolExecutionRuntime
from codeagent.core.context.preflight import ContextPreflightConfig
from codeagent.core.orchestration.config import AgentLoopConfig

from ..model.factory import (
    DEFAULT_RESERVE_TOKENS,
    ChatModelPort,
    _resolve_context_budget_metadata,
    resolve_model_capabilities,
)
from ..model import selection as model_selection
from ..policy import _create_policy
from ..prompts import _build_system_prompt, _load_skills
from .extensions import RuntimeExtensions, normalize_runtime_extensions
from codeagent.tools.capabilities import detect_tool_capabilities
from ..tools.factory import resolve_tool_resource_limits
from codeagent.tools.shared import ToolResourceLimits
from .tool_assembly import assemble_runtime_tools

class AgentRuntime:
    """一个模型/工具端口集合的资源所有者。"""

    def __init__(
        self,
        config: AgentLoopConfig,
        policy: Any,
        model_client: Any,
        mcp_tools: list[Any],
        tool_runtime: ToolExecutionRuntime | None = None,
    ) -> None:
        self.config = config
        self.policy = policy
        self.model_client = model_client
        self.mcp_tools = list(mcp_tools)
        self.tool_runtime = tool_runtime or config.tool_runtime
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        # Runtime ownership is attached to the composition config instead of
        # being stored in process-global mutable state.
        setattr(config, "_runtime_owner", self)

    async def close(self) -> None:
        """关闭模型和 MCP 资源，重复调用安全。"""
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_resources())
        await asyncio.shield(self._close_task)

    async def _close_resources(self) -> None:
        """Run the single shared close sequence for all concurrent callers."""
        try:
            if self.tool_runtime is not None:
                await self.tool_runtime.cancel_all()
            close_mcp = None
            try:
                from codeagent.tools.mcp.loader import close_mcp_tools

                close_mcp = close_mcp_tools
            except ImportError:  # pragma: no cover - optional SDK boundary
                pass
            if close_mcp is not None:
                await asyncio.to_thread(close_mcp, self.mcp_tools)
            await _close_resource(self.model_client)
        finally:
            if getattr(self.config, "_runtime_owner", None) is self:
                delattr(self.config, "_runtime_owner")

    def close_sync(self) -> asyncio.Task[None] | None:
        """同步关闭；已有事件循环时返回可等待的关闭任务。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
            return None
        else:
            return loop.create_task(self.close())


class _LegacyRuntimeIndex:
    """接受旧测试/扩展的注册写法，但不持有全局 runtime 状态。"""

    def __setitem__(self, key: int, value: AgentRuntime) -> None:
        del key, value

    def pop(self, key: int, default: Any = None) -> Any:
        del key
        return default


_RUNTIMES_BY_CONFIG = _LegacyRuntimeIndex()


async def _close_resource(resource: Any) -> None:
    """Await async close or run a blocking close without blocking the loop."""
    close = getattr(resource, "aclose", None)
    if callable(close):
        result = close()
        if inspect.isawaitable(result):
            await result
        return
    close = getattr(resource, "close", None)
    if callable(close):
        result = await asyncio.to_thread(close)
        if inspect.isawaitable(result):
            await result


def runtime_for_config(config: Any) -> AgentRuntime | None:
    """解析配置对应的资源所有者，兼容 lazy config wrapper。"""
    values = vars(config) if hasattr(config, "__dict__") else {}
    if "_real" in values:
        if values["_real"] is None:
            return None
        config = values["_real"]
    runtime = getattr(config, "_runtime_owner", None)
    return runtime if isinstance(runtime, AgentRuntime) else None


def close_runtime_for_config(config: Any) -> asyncio.Task[None] | None:
    """同步关闭配置对应的 runtime；事件循环内返回关闭任务。"""
    runtime = runtime_for_config(config)
    if runtime is not None:
        return runtime.close_sync()
    return None


async def close_runtime_for_config_async(config: Any) -> None:
    """Await closure of the runtime owned by a configuration."""
    runtime = runtime_for_config(config)
    if runtime is not None:
        await runtime.close()


def policy_for_config(config: Any) -> Any:
    """Return the policy owned by a config, including lazy configs."""
    runtime = runtime_for_config(config)
    if runtime is not None:
        return runtime.policy
    return _LazyPolicy(config)


def _system_prompt_for(
    cfg: Any,
    skills: list[Any],
    suffix: str | None,
) -> str:
    prompt = _build_system_prompt(cfg, skills)
    return f"{prompt}\n\n{suffix}" if suffix else prompt


def create_agent_config(
    cfg: Any = None,
    *,
    registry: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    approval_mode: str = "deny",
    mcp_diagnostics: list[str] | None = None,
    uncertain_budget_policy: str = "allow",
    context_preflight: ContextPreflightConfig | None = None,
    lifecycle_hooks: Iterable[LifecycleHook] | None = None,
    extensions: RuntimeExtensions | None = None,
    resource_limits: ToolResourceLimits | None = None,
    allowed_tool_names: Iterable[str] | None = None,
    subagent_runner: Any = None,
    system_prompt_suffix: str | None = None,
) -> AgentLoopConfig:
    """装配模型、工具执行器和独立安全策略。"""
    resolved_limits = resolve_tool_resource_limits(cfg, resource_limits)
    runtime_extensions = normalize_runtime_extensions(extensions, lifecycle_hooks)
    preflight_config = (
        context_preflight
        if context_preflight is not None
        else ContextPreflightConfig()
    )
    client = model_selection.create_llm(
        cfg=cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    skills, _diagnostics = _load_skills(cfg)
    system_prompt = _system_prompt_for(cfg, skills, system_prompt_suffix)
    adapted_tools, mcp_tools = assemble_runtime_tools(
        cfg,
        skills,
        resolved_limits,
        mcp_diagnostics,
        allowed_tool_names,
        subagent_runner,
    )
    tool_runtime = ToolExecutionRuntime(
        max_concurrency=resolved_limits.max_concurrency
    )
    budget_metadata = _resolve_context_budget_metadata(
        registry, cfg, provider, model
    )
    config = AgentLoopConfig(
        model=ChatModelPort(
            client,
            system_prompt=system_prompt,
            context_window=budget_metadata.context_window,
            output_reserve=budget_metadata.output_reserve,
            reserve_tokens=DEFAULT_RESERVE_TOKENS,
            window_source=budget_metadata.window_source,
            capabilities=resolve_model_capabilities(registry, cfg, provider, model),
        ),
        tools=adapted_tools,
        tool_runtime=tool_runtime,
        tool_timeout=resolved_limits.timeout,
        uncertain_budget_policy=uncertain_budget_policy,
        context_preflight=preflight_config,
        transform_context=runtime_extensions.transform_context or identity_context,
        context_preparer=runtime_extensions.context_preparer,
        context_budget=runtime_extensions.context_budget,
        context_transform_timeout=runtime_extensions.context_transform_timeout,
        before_tool_call=runtime_extensions.before_tool_call,
        after_tool_call=runtime_extensions.after_tool_call,
        lifecycle_hooks=runtime_extensions.lifecycle_hooks,
    )
    # Keep environment and AI metadata at the composition boundary.
    config.tool_capabilities = detect_tool_capabilities()
    config.tool_resource_limits = resolved_limits
    config.model_capabilities = config.model.capabilities
    AgentRuntime(config, _create_policy(cfg, approval_mode), client, mcp_tools, tool_runtime)
    return config


def create_agent_runtime(cfg: Any = None, **kwargs: Any) -> AgentRuntime:
    """创建需要显式生命周期控制的 Agent runtime。"""
    config = create_agent_config(cfg, **kwargs)
    runtime = runtime_for_config(config)
    if runtime is None:  # pragma: no cover - defensive registry invariant
        raise RuntimeError("AgentRuntime 装配失败")
    return runtime


class _LazyConfig:
    """首次访问属性时才构造模型客户端和工具。"""

    def __init__(self, factory: Callable[[], AgentLoopConfig]) -> None:
        self._factory = factory
        self._real: AgentLoopConfig | None = None

    def __getattr__(self, name: str) -> Any:
        if self._real is None:
            self._real = self._factory()
        return getattr(self._real, name)


class _LazyPolicy:
    """Resolve the composition policy only when a session first needs it."""

    def __init__(self, config: Any) -> None:
        self._config = config

    def decide(self, tool_name: str, args: dict[str, Any]) -> Any:
        getattr(self._config, "model")
        runtime = runtime_for_config(self._config)
        if runtime is None:  # pragma: no cover - defensive registry invariant
            raise RuntimeError("Agent 配置尚未完成装配")
        return runtime.policy.decide(tool_name, args)


class _LazySummarizer:
    """首次调用 summarize 时才创建摘要器客户端。"""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._real: Any = None

    async def summarize(
        self, messages: list[Any], prev_summary: str | None
    ) -> str:
        if self._real is None:
            self._real = self._factory()
        return await self._real.summarize(messages, prev_summary)

    async def aclose(self) -> None:
        """Close the real summarizer when it has been initialized."""
        if self._real is None:
            return
        close = getattr(self._real, "aclose", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
