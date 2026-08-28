"""Execute one model-requested tool and normalize its result."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from codeagent.core.context import AgentContext
from codeagent.core.awaiting import await_if_needed
from codeagent.core.events import AgentEvent, EventType
from codeagent.core.messages import (
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    new_id,
)
from codeagent.core.ports import AgentLoopConfig, ToolDecision


async def new_tool_result(
    tool: Any,
    call: ToolCall,
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], Any],
) -> ToolResult:
    """Run one AgentTool-shaped object and normalize its result."""
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
        return ToolResult(
            call.id,
            f"[工具执行出错] 未知工具: {call.name}",
            error=True,
            name=call.name,
            status=ToolExecutionStatus.FAILED,
            cleanup_confirmed=True,
        )
    if config.before_tool_call is not None:
        decision = await await_if_needed(config.before_tool_call(call, context))
        if isinstance(decision, ToolDecision) and decision.action != "allow":
            return ToolResult(
                call.id,
                f"[工具执行被拒绝] {decision.reason}",
                error=True,
                name=call.name,
                rejected=True,
                status=ToolExecutionStatus.REJECTED,
                cleanup_confirmed=True,
            )
    try:
        runtime = config.tool_runtime
        if runtime is not None:

            async def on_update(update: Any) -> None:
                emit(
                    AgentEvent(
                        EventType.TOOL_EXECUTION_UPDATE,
                        payload=update,
                        metadata={"tool_call_id": call.id, "tool_name": call.name},
                    )
                )

            result = await runtime.execute(
                tool,
                call,
                timeout=config.tool_timeout,
                operation_id=new_id(),
                on_update=on_update,
            )
            if config.after_tool_call is not None:
                updated = await await_if_needed(config.after_tool_call(call, result, context))
                if updated is not None:
                    result = updated
            return result

        execute = getattr(tool, "execute", None)
        if callable(execute):
            value = execute(call.id, call.args, signal=None, on_update=None)
            if config.tool_timeout is not None:
                value = await asyncio.wait_for(
                    await_if_needed(value), config.tool_timeout
                )
        else:
            args_obj = tool.Args(**call.args)
            method = getattr(tool, "ainvoke", None) or getattr(tool, "invoke_async", None)
            value = (
                method(args_obj)
                if method is not None
                else await asyncio.to_thread(tool.invoke, args_obj)
            )
        value = await await_if_needed(value)
        if isinstance(value, ToolResult):
            result = value
        elif isinstance(value, dict) and "content" in value:
            result = ToolResult(call.id, str(value["content"]), name=call.name)
        else:
            result = ToolResult(call.id, str(value), name=call.name)
    except Exception as exc:  # noqa: BLE001 - tool errors are model-visible
        result = ToolResult(
            call.id,
            f"[工具执行出错] {exc}",
            error=True,
            name=call.name,
            status=ToolExecutionStatus.FAILED,
            cleanup_confirmed=True,
        )
    if config.after_tool_call is not None:
        updated = await await_if_needed(config.after_tool_call(call, result, context))
        if updated is not None:
            result = updated
    return result


__all__ = ["new_tool_result"]
