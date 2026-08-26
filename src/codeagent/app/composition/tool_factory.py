"""内建工具和 MCP 工具的组合根装配。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from codeagent.ai.model.types import ToolDefinition
from codeagent.core.messages import ToolExecutionStatus, ToolResult


class AgentToolAdapter:
    """Adapt an existing schema-based tool to the core AgentTool contract."""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = str(getattr(tool, "name", ""))
        self.description = str(getattr(tool, "description", ""))
        self.parameters = ToolDefinition.from_tool(tool).parameters

    def __getattr__(self, name: str) -> Any:
        """Keep legacy lifecycle/diagnostic attributes visible to hosts."""
        return getattr(self._tool, name)

    async def execute(
        self,
        tool_call_id: str,
        arguments: dict[str, Any],
        *,
        signal: Any = None,
        on_update: Any = None,
    ) -> ToolResult:
        try:
            args = self._tool.Args(**arguments)
        except Exception as exc:  # noqa: BLE001 - schema diagnostics are model-visible
            return ToolResult(
                tool_call_id,
                f"[工具参数错误] {exc}",
                error=True,
                name=self.name,
                status=ToolExecutionStatus.INVALID_ARGUMENTS,
                cleanup_confirmed=True,
            )
        try:
            method = getattr(self._tool, "ainvoke", None) or getattr(
                self._tool, "invoke_async", None
            )
            if method is not None:
                value = method(args)
                value = await value if inspect.isawaitable(value) else value
            else:
                value = await asyncio.to_thread(self._tool.invoke, args)
            return ToolResult(
                tool_call_id,
                str(value),
                name=self.name,
                cleanup_confirmed=True,
            )
        except Exception as exc:  # noqa: BLE001 - one tool failure is isolated
            return ToolResult(
                tool_call_id,
                f"[工具执行出错] {exc}",
                error=True,
                name=self.name,
                status=ToolExecutionStatus.FAILED,
                cleanup_confirmed=True,
            )


def adapt_tools(tools: list[Any]) -> list[AgentToolAdapter]:
    """Return AgentTool adapters for legacy schema-based tools."""
    return [
        tool
        if isinstance(tool, AgentToolAdapter) or callable(getattr(tool, "execute", None))
        else AgentToolAdapter(tool)
        for tool in tools
    ]


def create_tools(cfg: Any = None, skills: dict[str, str] | None = None) -> list[Any]:
    """装配内建原子工具，并注入 Skill 渲染注册表。"""
    from codeagent.tools.registry import make_tools

    return make_tools(cfg, skills=skills)


def _load_mcp_tools(cfg: Any = None) -> tuple[list[Any], list[str]]:
    """加载 MCP 工具及诊断信息。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.tools.mcp.loader import load_mcp_tools

    return load_mcp_tools(CONFIG_DIR)
