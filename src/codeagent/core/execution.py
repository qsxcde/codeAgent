"""Controlled, framework-independent tool execution runtime.

The runtime accepts the new ``AgentTool`` protocol and keeps a compatibility
path for existing schema-based tools during migration.  It owns bounded
execution, operation state, timeout and cleanup reporting without importing a
concrete tool implementation.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any

from codeagent.core.messages import (
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    new_id,
)

__all__ = ["ToolExecutionRuntime", "ToolOperation"]


@dataclass
class ToolOperation:
    operation_id: str
    call_id: str
    tool_name: str
    status: str = "running"
    cleanup_confirmed: bool | None = None
    task: asyncio.Task[Any] | None = None


class ToolExecutionRuntime:
    """Bounded executor with per-operation status and cancellation tracking."""

    def __init__(self, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active: dict[str, ToolOperation] = {}

    @property
    def active_operations(self) -> dict[str, ToolOperation]:
        return dict(self._active)

    async def execute(
        self,
        tool: Any,
        call: ToolCall,
        timeout: float | None = None,
        operation_id: str | None = None,
        on_update: Any = None,
    ) -> ToolResult:
        operation = ToolOperation(operation_id or new_id(), call.id, call.name)
        self._active[operation.operation_id] = operation
        try:
            try:
                if callable(getattr(tool, "execute", None)):
                    args_obj = call.args
                else:
                    args_obj = tool.Args(**call.args)
            except Exception as exc:  # noqa: BLE001 - pydantic/schema error
                operation.status = ToolExecutionStatus.INVALID_ARGUMENTS
                operation.cleanup_confirmed = True
                return ToolResult(
                    call.id,
                    f"[工具参数错误] {exc}",
                    error=True,
                    name=getattr(tool, "name", call.name),
                    status=ToolExecutionStatus.INVALID_ARGUMENTS,
                    operation_id=operation.operation_id,
                    cleanup_confirmed=True,
                )

            async with self._semaphore:
                operation.task = asyncio.current_task()
                invoke = self._invoke(tool, args_obj, call, on_update=on_update)
                try:
                    if timeout is None:
                        content = await invoke
                    else:
                        content = await asyncio.wait_for(invoke, timeout=timeout)
                except asyncio.TimeoutError:
                    # ``wait_for`` can only preempt an async operation.  A
                    # thread-backed sync invoke continues in the background.
                    confirmed = self._is_cancellable(tool)
                    await self._cleanup(tool, operation)
                    operation.status = (
                        ToolExecutionStatus.TIMED_OUT
                        if confirmed
                        else ToolExecutionStatus.CLEANUP_UNCERTAIN
                    )
                    operation.cleanup_confirmed = confirmed
                    label = "超时并已清理" if confirmed else "停止等待但后台清理未确认"
                    return ToolResult(
                        call.id,
                        f"[工具执行超时] {label}",
                        error=True,
                        name=getattr(tool, "name", call.name),
                        status=operation.status,
                        operation_id=operation.operation_id,
                        cleanup_confirmed=confirmed,
                    )
                except asyncio.CancelledError:
                    await self._cleanup(tool, operation)
                    operation.status = ToolExecutionStatus.CANCELLED
                    operation.cleanup_confirmed = self._is_cancellable(tool)
                    raise
                except Exception as exc:  # noqa: BLE001 - one call is isolated
                    operation.status = ToolExecutionStatus.FAILED
                    operation.cleanup_confirmed = True
                    return ToolResult(
                        call.id,
                        f"[工具执行出错] {exc}",
                        error=True,
                        name=getattr(tool, "name", call.name),
                        status=ToolExecutionStatus.FAILED,
                        operation_id=operation.operation_id,
                        cleanup_confirmed=True,
                    )
                outcome_status = getattr(content, "status", None)
                outcome_cleanup = getattr(content, "cleanup_confirmed", True)
                content_text = getattr(content, "content", content)
                outcome_exit_code = getattr(content, "exit_code", None)
                outcome_duration_ms = int(getattr(content, "duration_ms", 0) or 0)
                outcome_truncated = bool(getattr(content, "output_truncated", False))
                outcome_success = getattr(content, "success", None)
                if outcome_status and outcome_status not in (
                    ToolExecutionStatus.OK,
                    "completed",
                ):
                    operation.status = str(outcome_status)
                    operation.cleanup_confirmed = outcome_cleanup
                    return ToolResult(
                        call.id,
                        str(content_text),
                        error=True,
                        name=getattr(tool, "name", call.name),
                        status=operation.status,
                        operation_id=operation.operation_id,
                        cleanup_confirmed=outcome_cleanup,
                        exit_code=outcome_exit_code,
                        duration_ms=outcome_duration_ms,
                        output_truncated=outcome_truncated,
                        semantic_success=outcome_success,
                    )
                operation.status = ToolExecutionStatus.OK
                operation.cleanup_confirmed = outcome_cleanup
                return ToolResult(
                    call.id,
                    str(content_text),
                    error=False,
                    name=getattr(tool, "name", call.name),
                    status=ToolExecutionStatus.OK,
                    operation_id=operation.operation_id,
                    cleanup_confirmed=True,
                    exit_code=outcome_exit_code,
                    duration_ms=outcome_duration_ms,
                    output_truncated=outcome_truncated,
                    semantic_success=outcome_success,
                )
        finally:
            self._active.pop(operation.operation_id, None)

    async def cancel(self, operation_id: str) -> bool:
        operation = self._active.get(operation_id)
        if operation is None:
            return False
        task = operation.task
        if task is not None and not task.done():
            task.cancel()
        return True

    async def cancel_all(self) -> None:
        for operation_id in list(self._active):
            await self.cancel(operation_id)

    def _invoke(
        self,
        tool: Any,
        args_obj: Any,
        call: ToolCall,
        *,
        on_update: Any = None,
    ) -> Any:
        """Return an awaitable for AgentTool or legacy schema-based tools."""
        agent_execute = getattr(tool, "execute", None)
        if callable(agent_execute):
            value = agent_execute(call.id, call.args, signal=None, on_update=on_update)
            return value if inspect.isawaitable(value) else _completed(value)
        for name in ("ainvoke", "invoke_async"):
            method = getattr(tool, name, None)
            if method is not None:
                value = method(args_obj)
                return value if inspect.isawaitable(value) else _completed(value)
        return asyncio.to_thread(tool.invoke, args_obj)

    @staticmethod
    def _is_cancellable(tool: Any) -> bool:
        return any(
            callable(getattr(tool, name, None))
            for name in ("execute", "ainvoke", "invoke_async")
        )

    async def _cleanup(self, tool: Any, operation: ToolOperation) -> None:
        for name in ("cancel_operation", "cancel", "cleanup"):
            method = getattr(tool, name, None)
            if not callable(method):
                continue
            try:
                value = method(operation.operation_id)
                if inspect.isawaitable(value):
                    await value
            except TypeError:
                try:
                    value = method()
                    if inspect.isawaitable(value):
                        await value
                except Exception:  # noqa: BLE001 - cleanup is best effort
                    pass
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass
            break


async def _completed(value: Any) -> Any:
    return value
