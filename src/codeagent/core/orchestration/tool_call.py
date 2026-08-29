"""Execute one model-requested AgentTool and apply runtime hooks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from codeagent.core.support.awaiting import await_if_needed
from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.errors import AgentRuntimeError
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import ToolCall, ToolExecutionStatus, ToolResult
from codeagent.core.contracts.ports import AgentTool, ToolDecision
from codeagent.core.orchestration.config import AgentLoopConfig


async def new_tool_result(
    tool: AgentTool | None,
    call: ToolCall,
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], Any],
) -> ToolResult:
    """Run one strictly adapted AgentTool and normalize its result."""
    if call.details.get("argument_error"):
        return ToolResult(
            call.id,
            f"[工具参数错误] {call.details['argument_error']}",
            error=True,
            name=call.name,
            status=ToolExecutionStatus.INVALID_ARGUMENTS,
            cleanup_confirmed=True,
        )
    if tool is None:
        return _unknown_tool_result(call)
    decision_result = await _check_before_hook(tool, call, context, config)
    if decision_result is not None:
        return decision_result
    try:
        result = await _execute_tool(tool, call, config, emit)
    except Exception as exc:  # noqa: BLE001 - tool errors are model-visible
        result = ToolResult(
            call.id,
            f"[工具执行出错] {exc}",
            error=True,
            name=call.name,
            status=ToolExecutionStatus.FAILED,
            cleanup_confirmed=True,
        )
    return await _check_after_hook(call, result, context, config)


async def _check_before_hook(
    tool: AgentTool,
    call: ToolCall,
    context: AgentContext,
    config: AgentLoopConfig,
) -> ToolResult | None:
    if config.before_tool_call is None:
        return None
    decision = await await_if_needed(config.before_tool_call(call, context))
    if isinstance(decision, ToolDecision) and decision.action != "allow":
        return ToolResult(
            call.id,
            f"[工具执行被拒绝] {decision.reason}",
            error=True,
            name=tool.name,
            rejected=True,
            status=ToolExecutionStatus.REJECTED,
            cleanup_confirmed=True,
        )
    return None


async def _execute_tool(
    tool: AgentTool,
    call: ToolCall,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], Any],
) -> ToolResult:
    runtime = config.tool_runtime
    if runtime is None:
        raise AgentRuntimeError("工具运行时未配置")

    async def on_update(update: Any) -> None:
        emit(
            AgentEvent(
                EventType.TOOL_EXECUTION_UPDATE,
                payload=update,
                metadata={"tool_call_id": call.id, "tool_name": call.name},
            )
        )

    return await runtime.execute(
        tool,
        call,
        timeout=config.tool_timeout,
        operation_id=None,
        on_update=on_update,
    )


async def _check_after_hook(
    call: ToolCall,
    result: ToolResult,
    context: AgentContext,
    config: AgentLoopConfig,
) -> ToolResult:
    if config.after_tool_call is None:
        return result
    updated = await await_if_needed(config.after_tool_call(call, result, context))
    return result if updated is None else updated


def _unknown_tool_result(call: ToolCall) -> ToolResult:
    return ToolResult(
        call.id,
        f"[工具执行出错] 未知工具: {call.name}",
        error=True,
        name=call.name,
        status=ToolExecutionStatus.FAILED,
        cleanup_confirmed=True,
    )


__all__ = ["new_tool_result"]
