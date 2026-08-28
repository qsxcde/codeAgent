"""ReAct 循环(自研版):for 循环驱动"模型→工具→继续/结束",事件直接 emit。

替代 langgraph 编排(2026-08-14,self-built-orchestration):
- 10 类 AgentEvent 在循环体内直接产出(翻译层消失);
- recursion_limit / abort / 工具超时均为普通代码;
- 工具结果按模型调用顺序写入当前内存上下文;
- 模块顶层零副作用,可被平台直接 import。

分层约束:core 不 import config / ai / tools / session;模型与工具经
``AgentLoopConfig`` 注入模型与工具;事件经调用方传入的 ``emit`` 回调分发
(AgentSession 传入 ``EventBus.emit``)。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from codeagent.core.awaiting import await_if_needed
from codeagent.core.events import AgentEvent, EventType
from codeagent.core.context import AgentContext
from codeagent.core.errors import (
    AgentContinueError,
    AgentRuntimeError,
    ContextPreparationError,
    ContextPreflightError,
)
from codeagent.core.messages import (
    CleanupStatus,
    Message,
    ToolCall,
    ToolResult,
)
from codeagent.core.model_request import new_model_message
from codeagent.core.ports import (
    AgentLoopConfig,
)
from codeagent.core.tool_invocation import new_tool_result

DEFAULT_RECURSION_LIMIT = 50


class RecursionLimitError(RuntimeError):
    """循环超限(替代 GraphRecursionError):session 壳捕获后回滚并友好提示。"""

    friendly = (
        "模型连续调用工具次数过多,已自动停止本轮并清理中间状态。"
        "请重试,或换一个更明确的指令。"
    )

    def __str__(self) -> str:
        return self.friendly


async def _run_agent_loop(
    context: AgentContext,
    config: AgentLoopConfig,
    prompt: str | None,
    *,
    emit: Callable[[AgentEvent], Any] | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
) -> list[Message]:
    emit = emit or (lambda _event: None)
    reset_cleanup = getattr(config.tool_runtime, "reset_cleanup_diagnostics", None)
    if callable(reset_cleanup):
        reset_cleanup()
    working = context.copy()
    new_messages: list[Message] = []
    if prompt is not None:
        user = Message(role="user", content=prompt)
        working.messages.append(user)
        new_messages.append(user)

    emit(AgentEvent(EventType.AGENT_START))
    try:
        for iteration in range(max(1, recursion_limit)):
            emit(AgentEvent(EventType.TURN_START, metadata={"turn_index": iteration}))
            assistant = await new_model_message(config, working.messages, emit)
            working.messages.append(assistant)
            new_messages.append(assistant)
            if not assistant.tool_calls:
                emit(AgentEvent(EventType.TURN_END, payload=assistant))
                break
            if iteration >= max(1, recursion_limit) - 1:
                raise RecursionLimitError()
            by_name = {getattr(tool, "name", ""): tool for tool in config.tools}
            results: list[ToolResult | None] = [None] * len(assistant.tool_calls)

            async def run_tool(index: int, call: ToolCall) -> tuple[int, ToolResult]:
                tool = by_name.get(call.name)
                emit(
                    AgentEvent(
                        EventType.TOOL_EXECUTION_START,
                        payload={"tool_call_id": call.id, "tool_name": call.name, "args": call.args},
                    )
                )
                return index, await new_tool_result(tool, call, working, config, emit)

            pending: list[asyncio.Task[tuple[int, ToolResult]]] = []
            if config.tool_execution == "parallel":
                pending = [
                    asyncio.create_task(run_tool(index, call))
                    for index, call in enumerate(assistant.tool_calls)
                ]
                completed = asyncio.as_completed(pending)
            else:
                completed = (
                    run_tool(index, call)
                    for index, call in enumerate(assistant.tool_calls)
                )
            try:
                for item in completed:
                    index, result = await item
                    results[index] = result
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
                            },
                        )
                    )
            except BaseException:
                for task in pending:
                    if not task.done():
                        task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                raise
            ordered_results = [result for result in results if result is not None]
            tool_messages = [
                Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=result.tool_call_id,
                )
                for result in ordered_results
            ]
            working.messages.extend(tool_messages)
            new_messages.extend(tool_messages)
            while config.steer_queue:
                steer = Message(
                    role="user",
                    content=config.steer_queue.pop(0),
                )
                working.messages.append(steer)
                new_messages.append(steer)
            emit(AgentEvent(EventType.TURN_END, payload=assistant, metadata={"tool_results": ordered_results}))
            if config.should_stop_after_turn is not None:
                stop = await await_if_needed(
                    config.should_stop_after_turn(assistant, ordered_results, working)
                )
                if stop:
                    break
        else:
            raise RecursionLimitError()
    except asyncio.CancelledError:
        metadata: dict[str, Any] = {}
        cleanup_status = getattr(config.tool_runtime, "cleanup_status", None)
        if cleanup_status and cleanup_status != CleanupStatus.NOT_REQUIRED:
            metadata["cleanup_status"] = cleanup_status
            metadata["cleanup_uncertain"] = bool(
                getattr(config.tool_runtime, "cleanup_uncertain", False)
            )
            cleanup_error = getattr(config.tool_runtime, "cleanup_error", None)
            if cleanup_error:
                metadata["cleanup_error"] = cleanup_error
        emit(AgentEvent(EventType.ABORTED, metadata=metadata))
        raise
    except Exception as exc:
        error_metadata = {"error_type": type(exc).__name__}
        if isinstance(exc, ContextPreparationError):
            error_metadata.update(
                {
                    "error_code": exc.code,
                    "phase": exc.phase,
                    "cause_type": type(exc.cause).__name__,
                }
            )
            if isinstance(exc, ContextPreflightError):
                snapshot = exc.result.snapshot
                error_metadata.update(
                    {
                        "budget_status": exc.result.status,
                        "budget_allowed": exc.result.allowed,
                        "input_tokens": snapshot.input_tokens,
                        "input_budget": snapshot.input_budget,
                        "headroom": snapshot.headroom,
                        "window_source": snapshot.window_source,
                        "warning_boundary": exc.result.warning_boundary,
                    }
                )
        emit(AgentEvent(EventType.ERROR, payload=str(exc), metadata=error_metadata))
        raise
    emit(AgentEvent(EventType.AGENT_END, payload=new_messages))
    return new_messages


async def run_agent_loop(
    context: AgentContext,
    config: AgentLoopConfig,
    prompt: str,
    *,
    emit: Callable[[AgentEvent], Any] | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
) -> list[Message]:
    """Run a new prompt against a copied in-memory context."""
    return await _run_agent_loop(
        context, config, prompt, emit=emit, recursion_limit=recursion_limit
    )


async def run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    *,
    emit: Callable[[AgentEvent], Any] | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
) -> list[Message]:
    """Continue from a user/tool-result tail without adding a prompt."""
    context.validate_continue()
    return await _run_agent_loop(
        context, config, None, emit=emit, recursion_limit=recursion_limit
    )
