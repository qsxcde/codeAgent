"""Execute one assistant tool-call batch with stable result ordering."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import (
    CleanupStatus,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    new_id,
)
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.core.orchestration.tool_call import new_tool_result


async def execute_tool_batch(
    calls: list[ToolCall],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], Any],
) -> list[ToolResult]:
    """Run calls according to config while returning them in model order."""
    by_name = {tool.name: tool for tool in config.tools}
    results: list[ToolResult | None] = [None] * len(calls)
    pending: list[asyncio.Task[tuple[int, ToolResult]]] = []
    operation_ids = [new_id() for _ in calls]
    started_indices: set[int] = set()
    emitted_end_indices: set[int] = set()

    _emit_queued_calls(calls, operation_ids, emit)

    async def run_tool(index: int, call: ToolCall) -> tuple[int, ToolResult]:
        def emit_for_call(event: AgentEvent) -> None:
            if event.type == EventType.TOOL_EXECUTION_START:
                started_indices.add(index)
            emit(event)

        result = await new_tool_result(
            by_name.get(call.name),
            call,
            context,
            config,
            emit_for_call,
            operation_id=operation_ids[index],
        )
        return index, result

    try:
        completed: Any
        if config.tool_execution == "parallel":
            pending = [
                asyncio.create_task(run_tool(index, call))
                for index, call in enumerate(calls)
            ]
            completed = asyncio.as_completed(pending)
        else:
            completed = (run_tool(index, call) for index, call in enumerate(calls))
        for item in completed:
            index, result = await item
            results[index] = result
            emitted_end_indices.add(index)
            _emit_tool_end(result, emit)
    except asyncio.CancelledError:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for index, call in enumerate(calls):
            if index in emitted_end_indices:
                continue
            _emit_tool_end(
                _cancelled_result(
                    call,
                    operation_ids[index],
                    config,
                    cleanup_required=index in started_indices,
                ),
                emit,
                synthetic_cancelled=True,
            )
            emitted_end_indices.add(index)
        raise
    except BaseException:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        raise
    return [result for result in results if result is not None]


def _emit_queued_calls(
    calls: list[ToolCall],
    operation_ids: list[str],
    emit: Callable[[AgentEvent], Any],
) -> None:
    """Publish the queue snapshot before any call can acquire a slot."""
    for index, call in enumerate(calls):
        operation_id = operation_ids[index]
        metadata = {
            "tool_call_id": call.id,
            "tool_name": call.name,
            "operation_id": operation_id,
            "status": "queued",
            "queue_position": index,
            "elapsed_ms": 0,
        }
        emit(
            AgentEvent(
                EventType.TOOL_EXECUTION_QUEUED,
                payload={"tool_call_id": call.id, "tool_name": call.name, "args": call.args},
                metadata=metadata,
                tool_call_id=call.id,
                operation_id=operation_id,
                status="queued",
                tool_name=call.name,
                queue_position=index,
                elapsed_ms=0,
            )
        )


def _emit_tool_end(
    result: ToolResult,
    emit: Callable[[AgentEvent], Any],
    *,
    synthetic_cancelled: bool = False,
) -> None:
    output_metadata = result.output_metadata.to_dict()
    emit(
        AgentEvent(
            EventType.TOOL_EXECUTION_END,
            payload=result,
            metadata={
                "tool_call_id": result.tool_call_id,
                "tool_name": result.name,
                "status": result.status,
                "error": result.error,
                "operation_id": result.operation_id,
                "cleanup_status": result.cleanup_status,
                "cleanup_uncertain": result.cleanup_uncertain,
                "cleanup_error": result.cleanup_error,
                "synthetic_cancelled": synthetic_cancelled,
                "output_metadata": output_metadata,
                **output_metadata,
            },
            tool_call_id=result.tool_call_id,
            operation_id=result.operation_id,
            status=result.status,
            tool_name=result.name,
            elapsed_ms=result.duration_ms,
            cleanup_status=result.cleanup_status,
            cleanup_uncertain=result.cleanup_uncertain,
        )
    )


def _cancelled_result(
    call: ToolCall,
    operation_id: str,
    config: AgentLoopConfig,
    *,
    cleanup_required: bool,
) -> ToolResult:
    """Close a queued or interrupted call when batch cancellation skips its result."""
    runtime = config.tool_runtime
    cleanup_status = (
        getattr(runtime, "cleanup_status", CleanupStatus.NOT_REQUIRED)
        if cleanup_required
        else CleanupStatus.NOT_REQUIRED
    )
    cleanup_uncertain = bool(
        cleanup_required and getattr(runtime, "cleanup_uncertain", False)
    )
    cleanup_confirmed = (
        False
        if cleanup_uncertain
        else cleanup_status == CleanupStatus.CONFIRMED
        if cleanup_required
        else None
    )
    return ToolResult(
        call.id,
        "[工具执行已取消]",
        error=True,
        name=call.name,
        status=ToolExecutionStatus.CANCELLED,
        operation_id=operation_id,
        cleanup_confirmed=cleanup_confirmed,
        cleanup_status=cleanup_status,
        cleanup_error=getattr(runtime, "cleanup_error", None) if cleanup_required else None,
    )


__all__ = ["execute_tool_batch"]
