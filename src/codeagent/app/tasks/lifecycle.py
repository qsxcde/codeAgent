"""任务监督器的 Agent 回合和验证修复生命周期。"""

from __future__ import annotations

import asyncio

from .modes import TaskMode
from .verification.models import TaskStatus, WorkspaceDiff

from .results import TaskEvent, TaskPhase, TaskResult


class TaskLifecycleMixin:
    async def run(
        self,
        text: str,
        *,
        mode: TaskMode = TaskMode.AUTO,
        verify_command: str | None = None,
    ) -> TaskResult:
        self._active_task = asyncio.current_task()
        self._cancelled = False
        mode = mode if isinstance(mode, TaskMode) else TaskMode(str(mode))
        self._emit(TaskEvent(TaskPhase.PLANNING, message="准备任务"))
        try:
            return await self._run_lifecycle(text, mode, verify_command)
        except asyncio.CancelledError:
            self._cancelled = True
            return self._terminal(TaskStatus.CANCELLED, mode, "任务已取消")
        finally:
            self._active_task = None
            self._child_task = None

    async def _run_lifecycle(
        self, text: str, mode: TaskMode, verify_command: str | None
    ) -> TaskResult:
        baseline = await self._capture_baseline(mode)
        await self._run_agent(text, mode)
        if self._cancelled:
            return self._terminal(TaskStatus.CANCELLED, mode, "任务已取消")
        if getattr(self.session, "last_failure", None):
            return self._terminal(TaskStatus.FAILED, mode, "Agent 回合失败")
        if baseline is None:
            return self._terminal(TaskStatus.NO_CHANGES, mode, "只读模式无需工作区验证")
        after = await asyncio.to_thread(self.inspector.capture)
        diff = self.inspector.compare(baseline, after)
        if not diff.has_changes:
            return self._terminal(TaskStatus.NO_CHANGES, mode, "工作区没有实际变更")
        return await self._verify_changes(baseline, diff, mode, verify_command)

    async def _verify_changes(
        self,
        baseline: object,
        diff: WorkspaceDiff,
        mode: TaskMode,
        verify_command: str | None,
    ) -> TaskResult:
        selected = self.resolver.resolve(
            verify_command if verify_command is not None else self.verify_command,
            configured=self.configured_command,
        )
        if selected is None:
            return self._terminal(
                TaskStatus.UNVERIFIED,
                mode,
                "检测不到验证命令，请提供显式验证命令",
                diff,
            )
        repairs = 0
        seen_failures: set[str] = set()
        latest_diff = diff
        while True:
            result = await self._verify(selected.command, selected.source, repairs + 1)
            after = await asyncio.to_thread(self.inspector.capture)
            latest_diff = self.inspector.compare(baseline, after)
            if result.status is TaskStatus.VERIFIED:
                self._emit(TaskEvent(TaskPhase.COMPLETED, result=result, attempt=repairs + 1))
                return TaskResult(TaskStatus.VERIFIED, mode, latest_diff.changed_files, result, repairs, "验证通过")
            if result.status is TaskStatus.CANCELLED or self._cancelled:
                return TaskResult(TaskStatus.CANCELLED, mode, latest_diff.changed_files, result, repairs, "任务已取消")
            fingerprint = self._fingerprint(result, latest_diff)
            if fingerprint in seen_failures or repairs >= self.max_repairs:
                self._emit(TaskEvent(TaskPhase.FAILED, result=result, attempt=repairs + 1))
                return TaskResult(TaskStatus.FAILED, mode, latest_diff.changed_files, result, repairs, "验证失败，已停止自动修复")
            seen_failures.add(fingerprint)
            repairs += 1
            self._emit(
                TaskEvent(
                    TaskPhase.REPAIRING,
                    message="根据验证诊断修复",
                    command=selected.command,
                    attempt=repairs,
                    max_attempts=self.max_repairs,
                    result=result,
                )
            )
            await self._run_agent(self._repair_prompt(result, latest_diff), TaskMode.CODE)
            if self._cancelled:
                return TaskResult(TaskStatus.CANCELLED, mode, latest_diff.changed_files, result, repairs, "任务已取消")
