"""Execute one assistant tool-call batch with stable result ordering."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import ToolCall, ToolResult
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

    async def run_tool(index: int, call: ToolCall) -> tuple[int, ToolResult]:
        emit(
            AgentEvent(
                EventType.TOOL_EXECUTION_START,
                payload={
                    "tool_call_id": call.id,
                    "tool_name": call.name,
                    "args": call.args,
                },
            )
        )
        result = await new_tool_result(by_name.get(call.name), call, context, config, emit)
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
            _emit_tool_end(result, emit)
    except BaseException:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        raise
    return [result for result in results if result is not None]


def _emit_tool_end(result: ToolResult, emit: Callable[[AgentEvent], Any]) -> None:
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
                "output_metadata": output_metadata,
                **output_metadata,
            },
        )
    )


__all__ = ["execute_tool_batch"]
