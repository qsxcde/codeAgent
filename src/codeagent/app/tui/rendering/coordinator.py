"""TUI 渲染协调：帧调度、尺寸防抖、活动动画与 backend flush。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from ..ports.backend import TuiBackend
from ..state.model import TuiModel
from .event_buffer import TuiEventBuffer
from .scheduler import FrameScheduler, ResizeDebouncer


class TuiRenderCoordinator:
    """把模型渲染生命周期隔离于输入、会话和任务协调。"""

    def __init__(
        self,
        model: TuiModel,
        backend: TuiBackend,
        *,
        sync_status: Callable[[], None] | None = None,
        before_render: Callable[[], None] | None = None,
        target_fps: float = 30.0,
    ) -> None:
        self.model = model
        self.backend = backend
        self._sync_status = sync_status
        self._before_render = before_render
        self.frame_scheduler = FrameScheduler(target_fps=target_fps)
        self.resize_debouncer = ResizeDebouncer(self.schedule_render)
        self.render_pending = False
        self._render_handle: asyncio.Handle | None = None
        self._render_task: asyncio.Task[None] | None = None
        self._active_render_generation: int | None = None
        self.activity_task: asyncio.Task[None] | None = None
        self._render_generation = 0
        self._rendered_frames = 0
        self._dropped_frames = 0
        self._last_frame_ms = 0.0
        self._max_frame_ms = 0.0
        self._over_budget_frames = 0

    @property
    def render_generation(self) -> int:
        """Return the latest content invalidation generation."""
        return self._render_generation

    def performance_snapshot(self) -> dict[str, int | float]:
        """Return content-free frame diagnostics for tests and benchmarks."""
        return {
            "render_generation": self._render_generation,
            "rendered_frames": self._rendered_frames,
            "dropped_frames": self._dropped_frames,
            "last_frame_ms": self._last_frame_ms,
            "max_frame_ms": self._max_frame_ms,
            "over_budget_frames": self._over_budget_frames,
            "event_buffer_flushes": self.event_buffer_flushes,
        }

    @property
    def event_buffer_flushes(self) -> int:
        """Return the number of coalesced batches applied before frames."""
        before_render = self._before_render
        owner = getattr(before_render, "__self__", None)
        buffer = getattr(owner, "_event_buffer", None)
        return int(getattr(buffer, "flush_count", 0))

    def schedule_render(self) -> None:
        """合并渲染请求，并通过帧调度器限制刷新频率。"""
        self._render_generation += 1
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush_render()
            return
        if self._render_task is not None and not self._render_task.done():
            self.render_pending = True
            return
        if self.render_pending:
            return
        now = loop.time()
        if not self.frame_scheduler.request(now):
            last = self.frame_scheduler.last_completed_at
            delay = (
                max(0.0, self.frame_scheduler.interval - (now - last))
                if last is not None
                else 0.0
            )
            self.render_pending = True
            self._render_handle = loop.call_later(delay, self._start_render)
            return
        self.render_pending = True
        self._render_handle = loop.call_soon(self._start_render)

    def flush_render_now(self) -> None:
        """立即提交一帧,供必须先于异步任务启动的 UI 状态使用。"""
        self._render_generation += 1
        if self._render_handle is not None:
            self._render_handle.cancel()
            self._render_handle = None
        self._cancel_render_task()
        self.render_pending = False
        self.flush_render()

    def flush_render(self) -> None:
        """将模型当前视口和状态栏提交到 backend。"""
        self._cancel_render_task()
        started = time.perf_counter()
        generation = self._render_generation
        handle, self._render_handle = self._render_handle, None
        if handle is not None:
            handle.cancel()
        self.render_pending = False
        first_frame = int(self.model.render_stats["frames"]) == 0
        try:
            if self._before_render is not None:
                self._before_render()
            width, height = self.backend.transcript_size()
            if width <= 0 or height <= 0:
                return
            lines = self.model.render(width, height)
            if generation != self._render_generation:
                self._dropped_frames += 1
                return
            self.backend.render(lines)
            if self._sync_status is not None:
                self._sync_status()
            self.backend.set_status(self.model.status.render(width)[0])
            self._rendered_frames += 1
        finally:
            self._finish_frame(started, first_frame)

    def cancel_pending_render(self) -> None:
        """Cancel queued or cooperative work during backend shutdown."""
        if self._render_handle is not None:
            self._render_handle.cancel()
            self._render_handle = None
        self._cancel_render_task()
        self.render_pending = False
        self.frame_scheduler.pending = False

    def _start_render(self) -> None:
        """Start a scheduled frame without doing its preparation inline."""
        self._render_handle = None
        if self._render_task is not None and not self._render_task.done():
            self.render_pending = True
            return
        self.render_pending = False
        if not self._render_requires_cooperation():
            self.flush_render()
            return
        loop = asyncio.get_running_loop()
        generation = self._render_generation
        task = loop.create_task(self._flush_render_async(generation))
        self._render_task = task
        self._active_render_generation = generation
        task.add_done_callback(self._render_task_done)

    def _render_requires_cooperation(self) -> bool:
        """Use the model's cost estimate to keep trivial frames synchronous."""
        estimate = getattr(self.model, "render_requires_cooperation", None)
        if estimate is None:
            return True
        return bool(estimate())

    async def _flush_render_async(self, generation: int) -> None:
        """Prepare a scheduled frame cooperatively, then commit it atomically."""
        started = time.perf_counter()
        first_frame = int(self.model.render_stats["frames"]) == 0
        try:
            if self._before_render is not None:
                self._before_render()
            width, height = self.backend.transcript_size()
            if width <= 0 or height <= 0:
                return
            render_progressive = getattr(self.model, "render_progressive", None)
            if render_progressive is None:
                lines = self.model.render(width, height)
            else:
                lines = await render_progressive(width, height)
            if generation != self._render_generation:
                self._dropped_frames += 1
                return
            self.backend.render(lines)
            if self._sync_status is not None:
                self._sync_status()
            self.backend.set_status(self.model.status.render(width)[0])
            self._rendered_frames += 1
        finally:
            if self._render_task is asyncio.current_task():
                self._finish_frame(started, first_frame)

    def _render_task_done(self, task: asyncio.Task[None]) -> None:
        """Handle task completion and request a frame for invalidated state."""
        if self._render_task is not task:
            return
        self._render_task = None
        generation = self._active_render_generation
        self._active_render_generation = None
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as error:
            asyncio.get_running_loop().call_exception_handler(
                {
                    "message": "TUI render task failed",
                    "exception": error,
                    "task": task,
                }
            )
            return
        self.render_pending = False
        if generation is not None and self._render_generation != generation:
            self.schedule_render()

    def _cancel_render_task(self) -> None:
        task = self._render_task
        if task is None:
            return
        self._render_task = None
        self._active_render_generation = None
        if not task.done():
            task.cancel()

    def _finish_frame(self, started: float, first_frame: bool) -> None:
        self.frame_scheduler.complete()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._last_frame_ms = round(elapsed_ms, 3)
        self._max_frame_ms = max(self._max_frame_ms, elapsed_ms)
        if elapsed_ms > self.frame_scheduler.interval * 1000:
            self._over_budget_frames += 1
        if first_frame:
            self.frame_scheduler.last_completed_at = None

    def sync_activity_timer(self) -> None:
        """只在活动提示可见时运行低频 UI 动画。"""
        if not self.model.activity_visible:
            self.stop_activity_timer()
            return
        if self.activity_task is not None and not self.activity_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self.activity_task = loop.create_task(self.animate_activity())

    def stop_activity_timer(self) -> None:
        task = self.activity_task
        self.activity_task = None
        if task is not None and not task.done():
            task.cancel()

    async def animate_activity(self) -> None:
        try:
            while self.model.activity_visible:
                await asyncio.sleep(0.45)
                if not self.model.activity_visible:
                    break
                self.model.advance_activity()
                self.schedule_render()
        finally:
            if self.activity_task is asyncio.current_task():
                self.activity_task = None
