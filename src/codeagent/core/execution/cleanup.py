"""Cleanup hooks and diagnostics for tool execution."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from codeagent.core.contracts.messages import CleanupStatus
from codeagent.core.execution.state import ToolOperation
from codeagent.core.contracts.ports import AgentTool, ToolCleanupPort

__all__ = ["CleanupResult", "CleanupTracker"]


@dataclass(frozen=True)
class CleanupResult:
    """Outcome of one cleanup attempt."""

    status: str
    error: str | None = None


class CleanupTracker:
    """Keep the most conservative cleanup fact seen in one runtime."""

    _RANK = {
        CleanupStatus.NOT_REQUIRED: 0,
        CleanupStatus.CONFIRMED: 1,
        CleanupStatus.PENDING: 2,
        CleanupStatus.FAILED: 3,
        CleanupStatus.UNCERTAIN: 3,
        CleanupStatus.UNSUPPORTED: 3,
    }

    def __init__(self) -> None:
        self.status = CleanupStatus.NOT_REQUIRED
        self.error: str | None = None

    @property
    def uncertain(self) -> bool:
        return self.status in {
            CleanupStatus.FAILED,
            CleanupStatus.UNCERTAIN,
            CleanupStatus.UNSUPPORTED,
        }

    def reset(self) -> None:
        self.status = CleanupStatus.NOT_REQUIRED
        self.error = None

    async def cleanup(
        self,
        tool: AgentTool,
        operation: ToolOperation,
        *,
        preemptible: bool,
    ) -> CleanupResult:
        """Invoke the optional strict-tool cleanup hook, if present."""
        operation.cleanup_status = CleanupStatus.PENDING
        if isinstance(tool, ToolCleanupPort):
            try:
                value = tool.cleanup(operation.operation_id)
                if inspect.isawaitable(value):
                    value = await value
                if value is False:
                    raise RuntimeError("cleanup hook returned false")
                return self._finish(operation, CleanupStatus.CONFIRMED)
            except Exception as exc:  # noqa: BLE001 - cleanup is diagnostic
                return self._finish(operation, CleanupStatus.FAILED, str(exc))

        status = CleanupStatus.CONFIRMED if preemptible else CleanupStatus.UNSUPPORTED
        return self._finish(operation, status)

    def record(self, result: CleanupResult) -> None:
        """Record the most conservative cleanup result."""
        if self._RANK[result.status] >= self._RANK[self.status]:
            self.status = result.status
            if result.error:
                self.error = result.error

    @staticmethod
    def _finish(
        operation: ToolOperation,
        status: str,
        error: str | None = None,
    ) -> CleanupResult:
        operation.cleanup_status = status
        operation.cleanup_error = error
        return CleanupResult(status, error)
