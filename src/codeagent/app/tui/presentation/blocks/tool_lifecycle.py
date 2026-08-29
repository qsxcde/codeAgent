"""工具块的生命周期状态与结果投影。"""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.messages import CleanupStatus, ToolOutputMetadata
from codeagent.core.contracts.tool_status import ToolLifecycleStatus

from ..output import OutputBuffer, OutputMetadata

__all__ = ["ToolLifecycleMixin"]


class ToolLifecycleMixin:
    """为工具展示块提供单向、幂等的生命周期状态迁移。"""

    def _set_cleanup_status(self, value: Any, uncertain: bool = False) -> None:
        if uncertain and value in (None, CleanupStatus.NOT_REQUIRED, CleanupStatus.CONFIRMED):
            value = CleanupStatus.UNCERTAIN
        if value in (None, ""):
            return
        normalized = str(value)
        if normalized in CleanupStatus.ALL:
            self.cleanup_status = normalized

    def set_execution_status(
        self,
        status: str,
        *,
        cleanup_status: str | None = None,
        cleanup_uncertain: bool = False,
        elapsed_ms: int | None = None,
        queue_position: int | None = None,
        error_code: str | None = None,
        progress_text: str | None = None,
    ) -> None:
        """Apply a lifecycle fact without allowing terminal state regression."""
        try:
            normalized = ToolLifecycleStatus.normalize(status)
        except ValueError:
            normalized = str(status or ToolLifecycleStatus.RUNNING)
        current = self.execution_status
        can_change = current not in ToolLifecycleStatus.TERMINAL and not (
            normalized == ToolLifecycleStatus.QUEUED
            and getattr(self, "_lifecycle_seen", False)
        )
        if can_change:
            self.execution_status = normalized
            self._lifecycle_seen = True
            self._sync_presentation_state()
        self._set_cleanup_status(cleanup_status, uncertain=cleanup_uncertain)
        if elapsed_ms is not None:
            self.elapsed_ms = max(0, int(elapsed_ms))
        if queue_position is not None:
            self.queue_position = max(0, int(queue_position))
        if error_code:
            self.error_code = str(error_code)
        if progress_text and current not in ToolLifecycleStatus.TERMINAL:
            self.progress_text = str(progress_text)
        self.touch()

    def _sync_presentation_state(self) -> None:
        if self.execution_status == ToolLifecycleStatus.AWAITING_CONFIRMATION:
            self.status = "pending"
            self.awaiting = True
        elif self.execution_status in ToolLifecycleStatus.TERMINAL:
            self.status = "done" if self.execution_status == ToolLifecycleStatus.COMPLETED else "error"
            self.awaiting = False
        else:
            self.status = "pending"
            self.awaiting = False

    def set_queued(self, *, queue_position: int | None = None) -> None:
        self.set_execution_status(
            ToolLifecycleStatus.QUEUED,
            queue_position=queue_position,
        )

    def set_started(self, *, elapsed_ms: int | None = None) -> None:
        self.set_execution_status(ToolLifecycleStatus.RUNNING, elapsed_ms=elapsed_ms)

    def set_progress(
        self,
        *,
        elapsed_ms: int | None = None,
        progress_text: str | None = None,
    ) -> None:
        self.set_execution_status(
            ToolLifecycleStatus.RUNNING,
            elapsed_ms=elapsed_ms,
            progress_text=progress_text,
        )

    def set_awaiting(
        self,
        *,
        elapsed_ms: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.set_execution_status(
            ToolLifecycleStatus.AWAITING_CONFIRMATION,
            elapsed_ms=elapsed_ms,
            error_code=error_code,
        )

    def set_cancelled(
        self,
        *,
        cleanup_status: str | None = None,
        cleanup_uncertain: bool = False,
        elapsed_ms: int | None = None,
    ) -> None:
        self.set_execution_status(
            ToolLifecycleStatus.CANCELLED,
            cleanup_status=cleanup_status,
            cleanup_uncertain=cleanup_uncertain,
            elapsed_ms=elapsed_ms,
        )

    def set_rejected(self, result: str = "") -> None:
        if self._result_applied:
            return
        if self.execution_status in ToolLifecycleStatus.TERMINAL and (
            self.execution_status != ToolLifecycleStatus.REJECTED
        ):
            if result:
                self.set_result(result, error=True)
            return
        self.rejected = True
        self.set_execution_status(ToolLifecycleStatus.REJECTED)
        if result:
            self.result = result
            self._result_applied = True
        self.awaiting = False
        self.touch()

    def set_result(
        self,
        result: str,
        error: bool = False,
        execution_status: str | None = None,
        output_metadata: ToolOutputMetadata | OutputMetadata | dict[str, Any] | None = None,
        *,
        cleanup_status: str | None = None,
        cleanup_uncertain: bool = False,
        elapsed_ms: int | None = None,
        error_code: str | None = None,
    ) -> None:
        """Attach output once; a prior terminal lifecycle fact remains authoritative."""
        if self._result_applied:
            return
        self._result_applied = True
        self.result = result
        if output_metadata is None:
            metadata = OutputMetadata(
                total_bytes=len(result.encode("utf-8")),
                total_lines=len(result.splitlines()),
                shown_lines=len(result.splitlines()),
                completeness="unknown",
                source="legacy",
            )
        elif isinstance(output_metadata, OutputMetadata):
            metadata = output_metadata
        else:
            metadata = OutputMetadata.from_value(output_metadata)
        page_size = 40
        if isinstance(output_metadata, dict):
            try:
                page_size = max(1, int(output_metadata.get("page_size") or page_size))
            except (TypeError, ValueError):
                page_size = 40
        self.output_buffer = OutputBuffer(result, metadata=metadata, page_size=page_size)
        if self.execution_status not in ToolLifecycleStatus.TERMINAL:
            target = execution_status or (
                ToolLifecycleStatus.FAILED if error else ToolLifecycleStatus.COMPLETED
            )
            self.set_execution_status(
                target,
                cleanup_status=cleanup_status,
                cleanup_uncertain=cleanup_uncertain,
                elapsed_ms=elapsed_ms,
                error_code=error_code,
            )
            if self.execution_status not in ToolLifecycleStatus.ALL:
                self.status = "error" if error else "done"
        else:
            self._set_cleanup_status(cleanup_status, uncertain=cleanup_uncertain)
            if elapsed_ms is not None:
                self.elapsed_ms = max(0, int(elapsed_ms))
            if error_code:
                self.error_code = str(error_code)
        if self.execution_status not in ToolLifecycleStatus.TERMINAL:
            self.status = "error" if error else "done"
        self.awaiting = False
        self.touch()
