"""模型、工具和策略端口的运行时资源所有权与装配。"""

from __future__ import annotations

import atexit
import asyncio
from typing import Any, Callable

from codeagent.core.execution import ToolExecutionRuntime
from codeagent.core.ports import AgentLoopConfig

from .model_factory import ChatModelPort
from . import model_selection
from .policy_factory import _create_policy
from .prompt_builder import _build_system_prompt, _load_skills
from .tool_factory import _load_mcp_tools, adapt_tools, create_tools


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

    async def close(self) -> None:
        """关闭模型和 MCP 资源，重复调用安全。"""
        if self._closed:
            return
        self._closed = True
        config_id = id(self.config)
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
                close_mcp(self.mcp_tools)
            close = getattr(self.model_client, "aclose", None)
            if callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
        finally:
            # The registry is only an ownership index; a closed runtime must
            # not keep a provider/model graph alive or be reused by a switch.
            _RUNTIMES_BY_CONFIG.pop(config_id, None)

    def close_sync(self) -> None:
        """TUI 命令回调使用的同步生命周期适配。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
        else:
            loop.create_task(self.close())


_RUNTIMES_BY_CONFIG: dict[int, AgentRuntime] = {}


def runtime_for_config(config: Any) -> AgentRuntime | None:
    """解析配置对应的资源所有者，兼容 lazy config wrapper。"""
    real = getattr(config, "_real", None)
    if real is not None:
        config = real
    return _RUNTIMES_BY_CONFIG.get(id(config))


def close_runtime_for_config(config: Any) -> None:
    """同步关闭配置对应的 runtime。"""
    runtime = runtime_for_config(config)
    if runtime is not None:
        runtime.close_sync()


def policy_for_config(config: Any) -> Any:
    """Return the policy owned by a config, including lazy configs."""
    runtime = runtime_for_config(config)
    if runtime is not None:
        return runtime.policy
    return _LazyPolicy(config)


def create_agent_config(
    cfg: Any = None,
    *,
    registry: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    approval_mode: str = "deny",
    mcp_diagnostics: list[str] | None = None,
) -> AgentLoopConfig:
    """装配模型、工具执行器和独立安全策略。"""
    from codeagent.app.skills import format_skill_invocation
    from codeagent.tools.mcp.loader import close_mcp_tools

    client = model_selection.create_llm(
        cfg=cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    skills, _diagnostics = _load_skills(cfg)
    rendered_skills = {skill.name: format_skill_invocation(skill) for skill in skills}
    mcp_tools, mcp_diags = _load_mcp_tools(cfg)
    if mcp_diagnostics is not None:
        mcp_diagnostics.extend(mcp_diags)
    if mcp_tools:
        atexit.register(close_mcp_tools, mcp_tools)
    raw_tools = create_tools(cfg, skills=rendered_skills) + mcp_tools
    tool_runtime = ToolExecutionRuntime()
    config = AgentLoopConfig(
        model=ChatModelPort(client, system_prompt=_build_system_prompt(cfg, skills)),
        tools=adapt_tools(raw_tools),
        tool_runtime=tool_runtime,
    )
    runtime = AgentRuntime(config, _create_policy(cfg, approval_mode), client, mcp_tools, tool_runtime)
    _RUNTIMES_BY_CONFIG[id(config)] = runtime
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
