"""TUI 渲染协调：帧调度、尺寸防抖、活动动画与 backend flush。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace

from ..ports.backend import TuiBackend
from ..state.model import TuiModel
from .scheduler import FrameScheduler, ResizeDebouncer
from codeagent.core.contracts.events import AgentEvent, EventType


class TuiEventBuffer:
    """合并相邻展示增量，同时在结构事件前保持严格顺序。"""

    _MERGEABLE = {EventType.THINKING_DELTA, EventType.TEXT_DELTA}

    def __init__(self, apply: Callable[[AgentEvent], None]) -> None:
        self._apply = apply
        self._pending: AgentEvent | None = None

    def push(self, event: AgentEvent) -> None:
        if event.type not in self._MERGEABLE:
            self.flush()
            self._apply(event)
            return
        if self._pending is None:
            self._pending = replace(event, metadata=dict(event.metadata))
            return
        if self._pending.type != event.type:
            self.flush()
            self._pending = replace(event, metadata=dict(event.metadata))
            return
        self._pending = replace(
            self._pending,
            payload=f"{self._pending.payload or ''}{event.payload or ''}",
            metadata=dict(event.metadata),
        )

    def flush(self) -> None:
        pending, self._pending = self._pending, None
        if pending is not None:
            self._apply(pending)


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
        self.activity_task: asyncio.Task[None] | None = None

    def schedule_render(self) -> None:
        """合并渲染请求，并通过帧调度器限制刷新频率。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush_render()
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
            self._render_handle = loop.call_later(delay, self.flush_render)
            return
        self.render_pending = True
        self._render_handle = loop.call_soon(self.flush_render)

    def flush_render_now(self) -> None:
        """立即提交一帧,供必须先于异步任务启动的 UI 状态使用。"""
        if self._render_handle is not None:
            self._render_handle.cancel()
            self._render_handle = None
        self.render_pending = False
        self.flush_render()

    def flush_render(self) -> None:
        """将模型当前视口和状态栏提交到 backend。"""
        handle, self._render_handle = self._render_handle, None
        if handle is not None:
            handle.cancel()
        self.render_pending = False
        if self._before_render is not None:
            self._before_render()
        first_frame = int(self.model.render_stats["frames"]) == 0
        self.frame_scheduler.complete()
        width, height = self.backend.transcript_size()
        if width <= 0 or height <= 0:
            return
        lines = self.model.render(width, height)
        self.backend.render(lines)
        if self._sync_status is not None:
            self._sync_status()
        self.backend.set_status(self.model.status.render(width)[0])
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
