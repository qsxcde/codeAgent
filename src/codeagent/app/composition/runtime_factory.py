"""模型、工具和策略端口的运行时资源所有权与装配。"""

from __future__ import annotations

import atexit
import asyncio
from typing import Any, Callable

from codeagent.core.ports import AgentPorts

from .model_factory import ChatModelPort
from .policy_factory import _create_policy
from .prompt_builder import _build_system_prompt, _load_skills
from .tool_factory import _load_mcp_tools, create_tools


class AgentRuntime:
    """一个模型/工具端口集合的资源所有者。"""

    def __init__(self, ports: AgentPorts, model_client: Any, mcp_tools: list[Any]) -> None:
        self.ports = ports
        self.model_client = model_client
        self.mcp_tools = list(mcp_tools)
        self._closed = False

    async def close(self) -> None:
        """关闭模型和 MCP 资源，重复调用安全。"""
        if self._closed:
            return
        self._closed = True
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

    def close_sync(self) -> None:
        """TUI 命令回调使用的同步生命周期适配。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
        else:
            loop.create_task(self.close())


_RUNTIMES_BY_PORTS: dict[int, AgentRuntime] = {}


def runtime_for_ports(ports: Any) -> AgentRuntime | None:
    """解析端口对应的资源所有者，兼容 lazy port wrapper。"""
    real = getattr(ports, "_real", None)
    if real is not None:
        ports = real
    return _RUNTIMES_BY_PORTS.get(id(ports))


def close_runtime_for_ports(ports: Any) -> None:
    """同步关闭端口对应的 runtime。"""
    runtime = runtime_for_ports(ports)
    if runtime is not None:
        runtime.close_sync()


def create_agent_ports(
    cfg: Any = None,
    *,
    registry: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    approval_mode: str = "deny",
    mcp_diagnostics: list[str] | None = None,
) -> AgentPorts:
    """装配模型端口、工具集和安全策略。"""
    from codeagent.ai.factory import create_llm
    from codeagent.app.skills import format_skill_invocation
    from codeagent.tools.mcp.loader import close_mcp_tools

    client = create_llm(
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
    ports = AgentPorts(
        model=ChatModelPort(client, system_prompt=_build_system_prompt(cfg, skills)),
        tools=create_tools(cfg, skills=rendered_skills) + mcp_tools,
        policy=_create_policy(cfg, approval_mode),
    )
    runtime = AgentRuntime(ports, client, mcp_tools)
    _RUNTIMES_BY_PORTS[id(ports)] = runtime
    return ports


def create_agent_runtime(cfg: Any = None, **kwargs: Any) -> AgentRuntime:
    """创建需要显式生命周期控制的 Agent runtime。"""
    ports = create_agent_ports(cfg, **kwargs)
    runtime = runtime_for_ports(ports)
    if runtime is None:  # pragma: no cover - defensive registry invariant
        raise RuntimeError("AgentRuntime 装配失败")
    return runtime


class _LazyPorts:
    """首次访问属性时才构造模型客户端、工具和策略。"""

    def __init__(self, factory: Callable[[], AgentPorts]) -> None:
        self._factory = factory
        self._real: AgentPorts | None = None

    def __getattr__(self, name: str) -> Any:
        if self._real is None:
            self._real = self._factory()
        return getattr(self._real, name)


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

