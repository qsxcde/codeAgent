"""Controlled, framework-independent AgentTool execution runtime."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from codeagent.core.execution.cleanup import CleanupResult, CleanupTracker
from codeagent.core.execution.result import normalize_tool_result
from codeagent.core.execution.state import OperationRegistry, ToolOperation
from codeagent.core.contracts.messages import (
    CleanupStatus,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    new_id,
)
from codeagent.core.contracts.ports import AgentTool

__all__ = [
    "CleanupResult",
    "OperationRegistry",
    "ToolExecutionRuntime",
    "ToolOperation",
]


class ToolExecutionRuntime:
    """Bounded executor with per-operation status and cancellation tracking."""

    def __init__(self, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._registry = OperationRegistry()
        self._cleanup = CleanupTracker()

    @property
    def active_operations(self) -> dict[str, ToolOperation]:
        return self._registry.active

    @property
    def cleanup_status(self) -> str:
        """Aggregated cleanup status for the current execution boundary."""
        return self._cleanup.status

    @property
    def cleanup_error(self) -> str | None:
        """Most recent cleanup diagnostic, when cleanup did not succeed."""
        return self._cleanup.error

    @property
    def cleanup_uncertain(self) -> bool:
        return self._cleanup.uncertain

    def reset_cleanup_diagnostics(self) -> None:
        """Start a new run-level cleanup diagnostic boundary."""
        self._cleanup.reset()

    async def execute(
        self,
        tool: AgentTool,
        call: ToolCall,
        timeout: float | None = None,
        operation_id: str | None = None,
        on_update: Any = None,
        on_start: Any = None,
    ) -> ToolResult:
        operation = ToolOperation(operation_id or new_id(), call.id, call.name)
        self._registry.register(operation)
        try:
            if not isinstance(tool, AgentTool):
                return self._contract_error(call, operation)
            operation.task = asyncio.current_task()
            async with self._semaphore:
                operation.status = "running"
                if on_start is not None:
                    started = on_start(operation)
                    if inspect.isawaitable(started):
                        await started
                return await self._execute_in_slot(tool, call, operation, timeout, on_update)
        finally:
            self._registry.remove(operation.operation_id)

    async def _execute_in_slot(
        self,
        tool: AgentTool,
        call: ToolCall,
        operation: ToolOperation,
        timeout: float | None,
        on_update: Any,
    ) -> ToolResult:
        try:
            invocation = self._invoke(tool, call, on_update=on_update)
            content = await invocation if timeout is None else await asyncio.wait_for(
                invocation, timeout=timeout
            )
        except asyncio.TimeoutError:
            return await self._timeout_result(tool, call, operation)
        except asyncio.CancelledError:
            await self._cancelled(tool, operation)
            raise
        except Exception as exc:  # noqa: BLE001 - one call is isolated
            return self._execution_error(call, operation, tool.name, exc)
        result, cleanup = normalize_tool_result(call, tool.name, operation, content)
        self._cleanup.record(cleanup)
        return result

    def _invoke(
        self,
        tool: AgentTool,
        call: ToolCall,
        *,
        on_update: Any = None,
    ) -> Any:
        """Return an awaitable for the strict AgentTool execution entrypoint."""
        value = tool.execute(call.id, call.args, signal=None, on_update=on_update)
        return value if inspect.isawaitable(value) else _completed(value)

    async def _timeout_result(
        self,
        tool: AgentTool,
        call: ToolCall,
        operation: ToolOperation,
    ) -> ToolResult:
        cleanup = await self._cleanup_operation(tool, operation)
        operation.status = ToolExecutionStatus.TIMED_OUT
        operation.cleanup_confirmed = cleanup.status == CleanupStatus.CONFIRMED
        self._cleanup.record(cleanup)
        label = "已清理" if operation.cleanup_confirmed else "停止等待但后台清理未确认"
        return ToolResult(
            call.id,
            f"[工具执行超时] {label}",
            error=True,
            name=tool.name,
            status=operation.status,
            operation_id=operation.operation_id,
            cleanup_confirmed=operation.cleanup_confirmed,
            cleanup_status=cleanup.status,
            cleanup_error=cleanup.error,
        )

    async def _cancelled(self, tool: AgentTool, operation: ToolOperation) -> None:
        operation.cancellation_requested = True
        cleanup = await self._cleanup_operation(tool, operation)
        operation.status = ToolExecutionStatus.CANCELLED
        operation.cleanup_confirmed = cleanup.status == CleanupStatus.CONFIRMED
        self._cleanup.record(cleanup)

    async def _cleanup_operation(
        self,
        tool: AgentTool,
        operation: ToolOperation,
    ) -> CleanupResult:
        operation.cleanup_task = asyncio.current_task()
        return await self._cleanup.cleanup(
            tool,
            operation,
            preemptible=self._is_async_tool(tool),
        )

    @staticmethod
    def _is_async_tool(tool: AgentTool) -> bool:
        declared = getattr(tool, "supports_cancellation", None)
        return True if declared is None else bool(declared)

    @staticmethod
    def _contract_error(call: ToolCall, operation: ToolOperation) -> ToolResult:
        operation.status = ToolExecutionStatus.FAILED
        operation.cleanup_confirmed = True
        return ToolResult(
            call.id,
            "[工具契约错误] 工具必须通过 AgentTool.execute 适配后才能执行",
            error=True,
            name=call.name,
            status=ToolExecutionStatus.FAILED,
            operation_id=operation.operation_id,
            cleanup_confirmed=True,
        )

    @staticmethod
    def _execution_error(
        call: ToolCall,
        operation: ToolOperation,
        tool_name: str,
        error: Exception,
    ) -> ToolResult:
        operation.status = ToolExecutionStatus.FAILED
        operation.cleanup_confirmed = True
        return ToolResult(
            call.id,
            f"[工具执行出错] {error}",
            error=True,
            name=tool_name,
            status=ToolExecutionStatus.FAILED,
            operation_id=operation.operation_id,
            cleanup_confirmed=True,
            cleanup_status=CleanupStatus.CONFIRMED,
        )

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


async def _completed(value: Any) -> Any:
    return value
