"""与终端引擎无关的帧调度和 resize 防抖原语。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

__all__ = ["FrameScheduler", "ResizeDebouncer"]


class FrameScheduler:
    """合并连续刷新请求，并以目标帧率限制下一次刷新。"""

    def __init__(self, target_fps: float = 30.0) -> None:
        if target_fps <= 0:
            raise ValueError("target_fps must be positive")
        self.interval = 1.0 / target_fps
        self.pending = False
        self.last_completed_at: float | None = None

    def request(self, now: float | None = None) -> bool:
        """返回本次请求是否应安排新帧。"""
        current = time.monotonic() if now is None else now
        if self.pending:
            return False
        if (
            self.last_completed_at is not None
            and current - self.last_completed_at < self.interval
        ):
            return False
        self.pending = True
        return True

    def complete(self, now: float | None = None) -> None:
        """标记一帧完成，下一帧从完成时刻开始计时。"""
        self.pending = False
        self.last_completed_at = time.monotonic() if now is None else now


class ResizeDebouncer:
    """在终端 resize 突发结束后只调用一次回调。"""

    def __init__(self, callback: Callable[[], None], delay: float = 0.05) -> None:
        self._callback = callback
        self._delay = max(0.0, delay)
        self._handle: asyncio.TimerHandle | None = None

    def notify(self) -> None:
        """合并本轮事件，回调在稳定窗口后执行。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._callback()
            return
        if self._handle is not None:
            self._handle.cancel()
        self._handle = loop.call_later(self._delay, self._fire)

    def _fire(self) -> None:
        self._handle = None
        self._callback()

