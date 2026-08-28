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
    CleanupStatus,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    new_id,
)

__all__ = [
    "CleanupResult",
    "OperationRegistry",
    "ToolExecutionRuntime",
    "ToolOperation",
]


@dataclass
class ToolOperation:
    operation_id: str
    call_id: str
    tool_name: str
    status: str = "running"
    cleanup_confirmed: bool | None = None
    task: asyncio.Task[Any] | None = None
    cleanup_status: str = CleanupStatus.NOT_REQUIRED
    cleanup_error: str | None = None
    cancellation_requested: bool = False
    cleanup_task: asyncio.Task[Any] | None = None


@dataclass(frozen=True)
class CleanupResult:
    """Outcome of one cleanup attempt."""

    status: str
    error: str | None = None


class OperationRegistry:
    """Track active operations until execution and cleanup are finished."""

    def __init__(self) -> None:
        self._operations: dict[str, ToolOperation] = {}

    def register(self, operation: ToolOperation) -> None:
        self._operations[operation.operation_id] = operation

    def get(self, operation_id: str) -> ToolOperation | None:
        return self._operations.get(operation_id)

    def remove(self, operation_id: str) -> None:
        self._operations.pop(operation_id, None)

    @property
    def active(self) -> dict[str, ToolOperation]:
        return dict(self._operations)


class ToolExecutionRuntime:
    """Bounded executor with per-operation status and cancellation tracking."""

    def __init__(self, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._registry = OperationRegistry()
        self._last_cleanup_status = CleanupStatus.NOT_REQUIRED
        self._last_cleanup_error: str | None = None

    @property
    def active_operations(self) -> dict[str, ToolOperation]:
        return self._registry.active

    @property
    def cleanup_status(self) -> str:
        """Aggregated cleanup status for the current execution boundary."""
        return self._last_cleanup_status

    @property
    def cleanup_error(self) -> str | None:
        """Most recent cleanup diagnostic, when cleanup did not succeed."""
        return self._last_cleanup_error

    @property
    def cleanup_uncertain(self) -> bool:
        return self._last_cleanup_status in {
            CleanupStatus.FAILED,
            CleanupStatus.UNCERTAIN,
            CleanupStatus.UNSUPPORTED,
        }

    def reset_cleanup_diagnostics(self) -> None:
        """Start a new run-level cleanup diagnostic boundary."""
        self._last_cleanup_status = CleanupStatus.NOT_REQUIRED
        self._last_cleanup_error = None

    async def execute(
        self,
        tool: Any,
        call: ToolCall,
        timeout: float | None = None,
        operation_id: str | None = None,
        on_update: Any = None,
    ) -> ToolResult:
        operation = ToolOperation(operation_id or new_id(), call.id, call.name)
        self._registry.register(operation)
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

            operation.task = asyncio.current_task()
            async with self._semaphore:
                invoke = self._invoke(tool, args_obj, call, on_update=on_update)
                try:
                    if timeout is None:
                        content = await invoke
                    else:
                        content = await asyncio.wait_for(invoke, timeout=timeout)
                except asyncio.TimeoutError:
                    # ``wait_for`` can only preempt an async operation.  A
                    # thread-backed sync invoke continues in the background.
                    cleanup = await self._cleanup(
                        tool, operation, preemptible=self._is_async_tool(tool)
                    )
                    operation.status = (
                        ToolExecutionStatus.TIMED_OUT
                        if cleanup.status in {
                            CleanupStatus.CONFIRMED,
                            CleanupStatus.FAILED,
                        }
                        else ToolExecutionStatus.CLEANUP_UNCERTAIN
                    )
                    operation.cleanup_confirmed = cleanup.status == CleanupStatus.CONFIRMED
                    operation.cleanup_status = cleanup.status
                    self._record_cleanup(cleanup)
                    label = "已清理" if operation.cleanup_confirmed else "停止等待但后台清理未确认"
                    return ToolResult(
                        call.id,
                        f"[工具执行超时] {label}",
                        error=True,
                        name=getattr(tool, "name", call.name),
                        status=operation.status,
                        operation_id=operation.operation_id,
                        cleanup_confirmed=operation.cleanup_confirmed,
                        cleanup_status=cleanup.status,
                        cleanup_error=cleanup.error,
                    )
                except asyncio.CancelledError:
                    operation.cancellation_requested = True
                    cleanup = await self._cleanup(
                        tool, operation, preemptible=self._is_async_tool(tool)
                    )
                    operation.status = ToolExecutionStatus.CANCELLED
                    operation.cleanup_confirmed = cleanup.status == CleanupStatus.CONFIRMED
                    operation.cleanup_status = cleanup.status
                    self._record_cleanup(cleanup)
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
                        cleanup_status=CleanupStatus.CONFIRMED,
                    )
                outcome_status = getattr(content, "status", None)
                outcome_cleanup = getattr(content, "cleanup_confirmed", True)
                outcome_cleanup_status = getattr(content, "cleanup_status", "")
                if outcome_cleanup_status == CleanupStatus.NOT_REQUIRED:
                    outcome_cleanup_status = ""
                if outcome_cleanup_status in {
                    CleanupStatus.FAILED,
                    CleanupStatus.UNCERTAIN,
                    CleanupStatus.UNSUPPORTED,
                }:
                    outcome_cleanup = False
                elif outcome_cleanup_status == CleanupStatus.CONFIRMED:
                    outcome_cleanup = True
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
                    operation.cleanup_confirmed = (
                        False if outcome_cleanup is False else outcome_cleanup
                    )
                    operation.cleanup_status = outcome_cleanup_status or (
                        CleanupStatus.UNCERTAIN
                        if outcome_cleanup is False
                        else CleanupStatus.CONFIRMED
                    )
                    self._record_cleanup(
                        CleanupResult(operation.cleanup_status)
                    )
                    return ToolResult(
                        call.id,
                        str(content_text),
                        error=True,
                        name=getattr(tool, "name", call.name),
                        status=operation.status,
                        operation_id=operation.operation_id,
                        cleanup_confirmed=outcome_cleanup,
                        cleanup_status=operation.cleanup_status,
                        exit_code=outcome_exit_code,
                        duration_ms=outcome_duration_ms,
                        output_truncated=outcome_truncated,
                        semantic_success=outcome_success,
                    )
                operation.status = ToolExecutionStatus.OK
                operation.cleanup_confirmed = (
                    True if outcome_cleanup is None else outcome_cleanup
                )
                operation.cleanup_status = (
                    outcome_cleanup_status
                    or (
                        CleanupStatus.UNCERTAIN
                        if operation.cleanup_confirmed is False
                        else CleanupStatus.CONFIRMED
                    )
                )
                self._record_cleanup(CleanupResult(operation.cleanup_status))
                if operation.cleanup_confirmed is False:
                    operation.status = ToolExecutionStatus.CLEANUP_UNCERTAIN
                return ToolResult(
                    call.id,
                    str(content_text),
                    error=operation.cleanup_confirmed is False,
                    name=getattr(tool, "name", call.name),
                    status=operation.status,
                    operation_id=operation.operation_id,
                    cleanup_confirmed=operation.cleanup_confirmed,
                    cleanup_status=operation.cleanup_status,
                    exit_code=outcome_exit_code,
                    duration_ms=outcome_duration_ms,
                    output_truncated=outcome_truncated,
                    semantic_success=outcome_success,
                )
        finally:
            self._registry.remove(operation.operation_id)

    async def cancel(self, operation_id: str) -> bool:
        operation = self._registry.get(operation_id)
        if operation is None:
            return False
        operation.cancellation_requested = True
        task = operation.task
        if task is not None and not task.done():
            task.cancel()
        return True

    async def cancel_all(self) -> None:
        operations = list(self._registry.active.values())
        tasks: list[asyncio.Task[Any]] = []
        current = asyncio.current_task()
        for operation in operations:
            operation.cancellation_requested = True
            task = operation.task
            if task is not None and not task.done():
                task.cancel()
                if task is not current:
                    tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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
    def _is_async_tool(tool: Any) -> bool:
        declared = getattr(tool, "supports_cancellation", None)
        if declared is not None:
            return bool(declared)
        return any(
            callable(getattr(tool, name, None))
            for name in ("execute", "ainvoke", "invoke_async")
        )

    async def _cleanup(
        self,
        tool: Any,
        operation: ToolOperation,
        *,
        preemptible: bool,
    ) -> CleanupResult:
        operation.cleanup_status = CleanupStatus.PENDING
        operation.cleanup_task = asyncio.current_task()
        for name in ("cancel_operation", "cancel", "cleanup"):
            method = getattr(tool, name, None)
            if not callable(method):
                continue
            try:
                value = method(operation.operation_id)
                if inspect.isawaitable(value):
                    value = await value
                if value is False:
                    raise RuntimeError("cleanup hook returned false")
                operation.cleanup_status = CleanupStatus.CONFIRMED
                return CleanupResult(CleanupStatus.CONFIRMED)
            except TypeError:
                try:
                    value = method()
                    if inspect.isawaitable(value):
                        value = await value
                    if value is False:
                        raise RuntimeError("cleanup hook returned false")
                    operation.cleanup_status = CleanupStatus.CONFIRMED
                    return CleanupResult(CleanupStatus.CONFIRMED)
                except Exception as exc:  # noqa: BLE001 - cleanup is diagnostic
                    operation.cleanup_status = CleanupStatus.FAILED
                    operation.cleanup_error = str(exc)
                    return CleanupResult(CleanupStatus.FAILED, str(exc))
            except Exception as exc:  # noqa: BLE001 - cleanup is diagnostic
                operation.cleanup_status = CleanupStatus.FAILED
                operation.cleanup_error = str(exc)
                return CleanupResult(CleanupStatus.FAILED, str(exc))
        # An async invocation was cancelled and awaited by the runtime, so
        # the invocation itself is stopped even when no external cleanup hook
        # exists. A thread-backed sync invocation cannot make that claim.
        status = CleanupStatus.CONFIRMED if preemptible else CleanupStatus.UNSUPPORTED
        operation.cleanup_status = status
        return CleanupResult(status)

    def _record_cleanup(self, result: CleanupResult) -> None:
        """Keep the most conservative cleanup fact seen in this run."""
        rank = {
            CleanupStatus.NOT_REQUIRED: 0,
            CleanupStatus.CONFIRMED: 1,
            CleanupStatus.PENDING: 2,
            CleanupStatus.FAILED: 3,
            CleanupStatus.UNCERTAIN: 3,
            CleanupStatus.UNSUPPORTED: 3,
        }
        if rank[result.status] >= rank[self._last_cleanup_status]:
            self._last_cleanup_status = result.status
            if result.error:
                self._last_cleanup_error = result.error


async def _completed(value: Any) -> Any:
    return value
