"""Runtime coordination for asynchronously persisted Subagent records."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from codeagent.core.contracts.events import AgentEvent

from .async_boundary import AsyncPersistenceBoundary
from .subagent_record_model import SubagentRunRecord, fold_records
from .subagent_record_codec import record_from_event


class SubagentRecordCoordinator:
    """Deduplicate parent events and serialize their backend writes."""

    def __init__(
        self,
        append: Callable[[SubagentRunRecord], None],
        can_append: Callable[[], bool],
    ) -> None:
        self._append = append
        self._can_append = can_append
        self._records: dict[str, SubagentRunRecord] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._lock = asyncio.Lock()
        self._boundary = AsyncPersistenceBoundary()
        self._diagnostics: list[str] = []

    @property
    def records(self) -> list[SubagentRunRecord]:
        return list(self._records.values())

    @property
    def diagnostics(self) -> list[str]:
        return list(self._diagnostics)

    def restore(self, records: list[SubagentRunRecord]) -> None:
        self._records = {record.delegation_id: record for record in fold_records(records)}

    def record_diagnostic(self, message: str) -> None:
        self._record_diagnostic(message)

    def observe(self, event: AgentEvent, parent_run_id: str | None) -> None:
        """Accept one event without performing synchronous file I/O."""
        try:
            record = record_from_event(event, expected_parent_run_id=parent_run_id)
        except (TypeError, ValueError) as exc:
            self._record_diagnostic(f"事件转换失败: {exc}")
            return
        if record is None or not self._can_append():
            return
        previous = self._records.get(record.delegation_id)
        if previous is not None and previous.is_terminal:
            return
        if previous is not None and _record_signature(previous) == _record_signature(record):
            return
        self._records[record.delegation_id] = record
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                self._append(record)
            except Exception as exc:  # noqa: BLE001 - diagnostic-only persistence
                self._record_diagnostic(f"同步写入失败: {exc}")
            return
        task = loop.create_task(self._persist(record))
        self._tasks.append(task)
        task.add_done_callback(self._finish_task)

    async def drain(self) -> None:
        """Wait for all accepted record writes."""
        while self._tasks:
            tasks = tuple(self._tasks)
            gather = asyncio.gather(*tasks, return_exceptions=True)
            try:
                results = await asyncio.shield(gather)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(gather)
                except BaseException:
                    pass
                raise
            for result in results:
                if isinstance(result, Exception):
                    self._record_diagnostic(f"异步写入失败: {result}")
            for task in tasks:
                self._remove_task(task)

    async def _persist(self, record: SubagentRunRecord) -> None:
        try:
            async with self._lock:
                await self._boundary.run(lambda: self._append(record))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - parent result is independent
            self._record_diagnostic(f"异步写入失败: {exc}")

    def _finish_task(self, task: asyncio.Task[None]) -> None:
        self._remove_task(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._record_diagnostic(f"异步写入任务失败: {exception}")

    def _record_diagnostic(self, message: str) -> None:
        if len(self._diagnostics) < 8:
            self._diagnostics.append(str(message)[:2_000])

    def _remove_task(self, task: asyncio.Task[None]) -> None:
        try:
            self._tasks.remove(task)
        except ValueError:
            pass


def _record_signature(record: SubagentRunRecord) -> str:
    return json.dumps(
        {
            "delegation_id": record.delegation_id,
            "status": record.status,
            "phase": record.phase,
            "child_run_id": record.child_run_id,
            "attempt_id": record.attempt_id,
            "summary": record.summary,
            "reason_code": record.reason_code,
            "diagnostics": record.diagnostics,
            "cleanup_uncertain": record.cleanup_uncertain,
            "result": record.result,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


__all__ = ["SubagentRecordCoordinator"]
