"""Mutable state owned by the core tool execution runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from codeagent.core.contracts.messages import CleanupStatus

__all__ = ["OperationRegistry", "ToolOperation"]


@dataclass
class ToolOperation:
    """Track one active tool operation until execution and cleanup finish."""

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
