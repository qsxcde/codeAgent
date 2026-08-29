"""TUI 状态栏低频计时刷新调度。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..state.model import TuiModel


class StatusTimer:
    """让状态栏时钟独立于 Agent 事件流刷新,不触碰业务状态。"""

    def __init__(
        self,
        model: TuiModel,
        schedule_render: Callable[[], None],
        interval: float,
    ) -> None:
        self._model = model
        self._schedule_render = schedule_render
        self._interval = max(0.001, interval)
        self.task: asyncio.Task[None] | None = None

    def sync(self) -> None:
        """Start or stop the timer to match the current visible clock state."""
        if not self._model.status_clock_active:
            self.stop()
            return
        if self.task is not None and not self.task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self.task = loop.create_task(self.run())

    def stop(self) -> None:
        """Cancel the timer without waiting for another render frame."""
        task = self.task
        self.task = None
        if task is not None and not task.done():
            task.cancel()

    async def run(self) -> None:
        """Refresh display clocks and submit normal coalesced frames."""
        try:
            while self._model.status_clock_active:
                await asyncio.sleep(self._interval)
                if not self._model.status_clock_active:
                    break
                self._model.refresh_status_clock()
                self._schedule_render()
        finally:
            if self.task is asyncio.current_task():
                self.task = None
