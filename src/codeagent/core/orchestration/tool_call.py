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
    operation_id: str | None = None,
) -> ToolResult:
    """Run one strictly adapted AgentTool and normalize its result."""
    if call.details.get("argument_error"):
        return ToolResult(
            call.id,
            f"[工具参数错误] {call.details['argument_error']}",
            error=True,
            name=call.name,
            status=ToolExecutionStatus.INVALID_ARGUMENTS,
            operation_id=operation_id or "",
            cleanup_confirmed=True,
        )
    if tool is None:
        return _unknown_tool_result(call, operation_id)
    decision_result = await _check_before_hook(tool, call, context, config, operation_id)
    if decision_result is not None:
        return decision_result
    try:
        result = await _execute_tool(tool, call, config, emit, operation_id)
    except Exception as exc:  # noqa: BLE001 - tool errors are model-visible
        result = ToolResult(
            call.id,
            f"[工具执行出错] {exc}",
            error=True,
            name=call.name,
            status=ToolExecutionStatus.FAILED,
            operation_id=operation_id or "",
            cleanup_confirmed=True,
        )
    result = await _check_after_hook(call, result, context, config)
    if not result.operation_id:
        result.operation_id = operation_id or ""
    return result


async def _check_before_hook(
    tool: AgentTool,
    call: ToolCall,
    context: AgentContext,
    config: AgentLoopConfig,
    operation_id: str | None,
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
            operation_id=operation_id or "",
            cleanup_confirmed=True,
        )
    return None


async def _execute_tool(
    tool: AgentTool,
    call: ToolCall,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], Any],
    operation_id: str | None,
) -> ToolResult:
    runtime = config.tool_runtime
    if runtime is None:
        raise AgentRuntimeError("工具运行时未配置")

    async def on_update(update: Any) -> None:
        elapsed_ms = 0
        if isinstance(update, dict) and update.get("elapsed_ms") is not None:
            try:
                elapsed_ms = max(0, int(update["elapsed_ms"]))
            except (TypeError, ValueError):
                elapsed_ms = 0
        emit(
            AgentEvent(
                EventType.TOOL_EXECUTION_UPDATE,
                payload=update,
                metadata={
                    "tool_call_id": call.id,
                    "tool_name": call.name,
                    "operation_id": operation_id,
                    "status": "running",
                    "elapsed_ms": elapsed_ms,
                },
                tool_call_id=call.id,
                operation_id=operation_id,
                status="running",
                tool_name=call.name,
                elapsed_ms=elapsed_ms,
            )
        )

    def on_start(operation: Any) -> None:
        actual_operation_id = str(getattr(operation, "operation_id", operation_id or ""))
        metadata = {
            "tool_call_id": call.id,
            "tool_name": call.name,
            "operation_id": actual_operation_id,
            "status": "running",
            "elapsed_ms": 0,
        }
        emit(
            AgentEvent(
                EventType.TOOL_EXECUTION_START,
                payload={"tool_call_id": call.id, "tool_name": call.name, "args": call.args},
                metadata=metadata,
                tool_call_id=call.id,
                operation_id=actual_operation_id,
                status="running",
                tool_name=call.name,
                elapsed_ms=0,
            )
        )

    return await runtime.execute(
        tool,
        call,
        timeout=config.tool_timeout,
        operation_id=operation_id,
        on_update=on_update,
        on_start=on_start,
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


def _unknown_tool_result(call: ToolCall, operation_id: str | None) -> ToolResult:
    return ToolResult(
        call.id,
        f"[工具执行出错] 未知工具: {call.name}",
        error=True,
        name=call.name,
        status=ToolExecutionStatus.FAILED,
        operation_id=operation_id or "",
        cleanup_confirmed=True,
    )


__all__ = ["new_tool_result"]
