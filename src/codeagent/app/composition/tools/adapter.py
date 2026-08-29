"""Explicit boundary from legacy concrete tools to the core AgentTool port."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from codeagent.ai.model.types import ToolDefinition
from codeagent.app.errors.reporting import report_unexpected_error
from codeagent.core.contracts.messages import ToolExecutionStatus, ToolResult
from codeagent.core.contracts.ports import AgentTool

from .definitions import tool_definition_for


class AgentToolAdapter:
    """Adapt one schema-based Atomic/MCP tool to the core AgentTool contract."""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = str(getattr(tool, "name", ""))
        self.description = str(getattr(tool, "description", ""))
        definition = tool_definition_for(tool)
        self.parameters = definition.parameters

    @property
    def supports_cancellation(self) -> bool:
        """Expose whether the wrapped tool has a genuinely async path."""
        declared = getattr(self._tool, "supports_cancellation", None)
        if declared is not None:
            return bool(declared)
        return any(
            callable(getattr(self._tool, name, None))
            for name in ("ainvoke", "invoke_async")
        )

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
            report_unexpected_error("工具参数转换", exc)
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
                value = _call_with_hooks(method, args, signal, on_update)
                value = await value if inspect.isawaitable(value) else value
            else:
                value = await asyncio.to_thread(
                    _call_with_hooks,
                    self._tool.invoke,
                    args,
                    signal,
                    on_update,
                )
            return _result_from_value(tool_call_id, self.name, value)
        except Exception as exc:  # noqa: BLE001 - one tool failure is isolated
            report_unexpected_error("工具执行", exc)
            return ToolResult(
                tool_call_id,
                f"[工具执行出错] {exc}",
                error=True,
                name=self.name,
                status=ToolExecutionStatus.FAILED,
                cleanup_confirmed=True,
            )


def _result_from_value(tool_call_id: str, name: str, value: Any) -> ToolResult:
    if isinstance(value, ToolResult):
        return value
    if hasattr(value, "content"):
        status = str(getattr(value, "status", "") or "")
        return ToolResult(
            tool_call_id,
            str(getattr(value, "content", "")),
            error=bool(getattr(value, "error", False))
            or status not in {"", ToolExecutionStatus.OK, "completed"},
            name=name,
            status=status,
            cleanup_confirmed=getattr(value, "cleanup_confirmed", None),
            cleanup_status=getattr(value, "cleanup_status", ""),
            cleanup_error=getattr(value, "cleanup_error", None),
            exit_code=getattr(value, "exit_code", None),
            duration_ms=int(getattr(value, "duration_ms", 0) or 0),
            output_truncated=bool(getattr(value, "output_truncated", False)),
            semantic_success=getattr(value, "success", None),
        )
    return ToolResult(tool_call_id, str(value), name=name, cleanup_confirmed=True)


def _call_with_hooks(method: Any, args: Any, signal: Any, on_update: Any) -> Any:
    """Pass optional runtime hooks only when a concrete tool accepts them."""
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs = {}
    if signal is not None and (accepts_kwargs or "signal" in parameters):
        kwargs["signal"] = signal
    if on_update is not None and (accepts_kwargs or "on_update" in parameters):
        kwargs["on_update"] = on_update
    return method(args, **kwargs)


def adapt_tools(tools: list[Any]) -> list[AgentTool]:
    """Return explicit AgentTool adapters for concrete legacy tools."""
    return [
        tool
        if isinstance(tool, AgentToolAdapter) or isinstance(tool, AgentTool)
        else AgentToolAdapter(tool)
        for tool in tools
    ]


__all__ = ["AgentToolAdapter", "adapt_tools"]
