"""app/tui/application.py:TuiApp——装配协调器、注册 backend 回调并管理顶层生命周期。

具体输入、命令、会话、任务和渲染职责由同层协调器承接；本模块只保留
``TuiBackend`` 回调注册、事件桥接和退出生命周期。

分层约束:本模块可 import session/core/backend,禁止 import 具体引擎。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from codeagent.app.skills.models import Skill
from .ports.backend import TuiBackend
from .presentation.blocks import ToolCallBlock
from .state.model import TuiModel
from .presentation.status import FooterInfo
from .rendering.coordinator import TuiEventBuffer, TuiRenderCoordinator
from .commands.interaction import (
    TuiInteractionCoordinator,
    _SUGGESTION_WINDOW,
)
from .session.coordinator import TuiSessionCoordinator
from .session.conversation import TuiConversationCoordinator
from .commands.coordinator import TuiCommandCoordinator
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.app.tasks.modes import TaskMode
from codeagent.app.tasks.supervisor import TaskSupervisor

#: 退出文档的兜底宽度(视口尺寸不可用时)。
_DEFAULT_EXIT_WIDTH = 120

class TuiApp(
    TuiConversationCoordinator,
    TuiSessionCoordinator,
    TuiCommandCoordinator,
    TuiInteractionCoordinator,
):
    """把会话事件流驱动成组件渲染 + 输入/打断/退出的视图逻辑。"""

    @property
    def _activity_task(self) -> asyncio.Task[None] | None:
        """提供给测试和内部观测的活动任务视图。"""
        return self._render_coordinator.activity_task

    def __init__(
        self,
        manager: Any,
        backend: TuiBackend,
        footer: FooterInfo | None = None,
        rebuild_ports: Any = None,
        rebuild_ports_async: Any = None,
        candidates: dict[str, Any] | None = None,
        agents_sources: list[str] | None = None,
        skills: tuple[list[Skill], list[str]] | None = None,
        mcp_diagnostics: list[str] | None = None,
        save_key: Any = None,
        configured_providers: set[str] | None = None,
        refresh_skills: Callable[[], tuple[list[Skill], list[str]]] | None = None,
        package_action: Callable[[str, tuple[str, ...]], str] | None = None,
        close_runtime: Callable[[], None] | None = None,
    ) -> None:
        """初始化 TUI 状态、回调和组合根注入的适配器。"""
        self._manager = manager
        self._backend = backend
        self._rebuild_ports = rebuild_ports
        self._rebuild_ports_async = rebuild_ports_async
        self._candidates = candidates or {}
        self._agents_sources = agents_sources or []
        self._skills = list(skills[0]) if skills else []
        self._skill_diagnostics = list(skills[1]) if skills else []
        self._mcp_diagnostics = list(mcp_diagnostics or [])
        self._skills_by_name = {s.name: s for s in self._skills}
        self._save_key = save_key
        self._configured_providers = set(configured_providers or [])
        self._refresh_skills_callback = refresh_skills
        self._package_action = package_action
        self._close_runtime = close_runtime
        self._task_mode = TaskMode.AUTO
        self._task_active = False
        self._task_supervisor: TaskSupervisor | None = None
        #: 待输入密钥的 provider(/login 登录态;None = 普通输入)。
        self._login_pending: str | None = None
        self._suggestions: list[str] = []
        self._suggestion_index = 0
        #: 建议浮层候选语境:"command" = 命令名补全,"value" = picker 值候选。
        self._suggestion_kind = "command"
        # 确认填入后抑制下一次建议重算(set_input_text 的异步变更通知不重弹浮层,D1)。
        self._suppress_next_suggestions = False
        #: 最近一次输入内容(值语境确认时据此还原命令名)。
        self._last_text = ""
        self._provider = footer.provider if footer is not None else ""
        #: 当前待确认请求(confirmation_requested 的 payload;None = 无确认条)。
        self._pending_confirmation: dict[str, Any] | None = None
        self._restore_task: asyncio.Task[None] | None = None
        self._conversation_task: asyncio.Task[None] | None = None
        self._session_action_task: asyncio.Task[None] | None = None
        self._package_task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._unsubscribe: Callable[[], None] | None = None
        self._shutdown_started = False
        self._shutdown_complete = False
        self._accepting_input = True
        self.model = TuiModel()
        if footer is not None:
            # 底部状态栏装配数据在组合根解析固化(design D5):模型名/思考强度/工作目录。
            self.model.status.model = footer.model
            self.model.status.effort = footer.effort
            self.model.status.cwd = footer.cwd
        self._event_buffer = TuiEventBuffer(self._apply_event)
        self._render_coordinator = TuiRenderCoordinator(
            self.model,
            self._backend,
            sync_status=self._sync_context_status,
            before_render=self._event_buffer_flush,
        )
        self._hydrate_current_session()
        self._sync_context_status()
        self._unsubscribe = self._manager.subscribe(self._on_event)

    # -- 生命周期 ----------------------------------------------------------

    def start(self) -> None:
        """注册后端回调并进入事件循环(阻塞直到退出)。"""
        self._backend.on_submit(self._submit)
        self._backend.on_interrupt(self._interrupt)
        self._backend.on_quit(self._quit)
        self._backend.on_resize(self._render_coordinator.resize_debouncer.notify)
        self._backend.on_click(self._click)
        self._backend.on_input_changed(self._on_input_changed)
        self._backend.on_suggestion_navigate(self._on_suggestion_navigate)
        self._backend.on_suggestion_confirm(self._on_suggestion_confirm)
        self._backend.on_scroll(self._on_scroll)
        self._backend.on_confirmation_response(self._on_confirmation_response)
        self._backend.run()

    def _click(self, row: int) -> None:
        """点击 transcript 某行:若命中工具块则切换折叠(design D4)。"""
        block = self.model.transcript.block_at(row)
        if isinstance(block, ToolCallBlock):
            block.toggle_expand()
            self._schedule_render()

    def _on_scroll(self, delta: int) -> None:
        """滚动输入(滚轮/PageUp/PageDown)→ transcript 视口移动(design T-47)。

        ``Transcript.scroll`` 内处理 follow 翻转(上滚解除跟随),``render`` 内
        处理滚到底恢复跟随;引擎层已按焦点分派,这里无需区分输入来源。
        """
        self.model.transcript.scroll(delta)
        self._schedule_render()

    # -- 确认交互(security-permissions)-------------------------------------
    def _exit(self) -> None:
        """Schedule async shutdown from the synchronous backend callback."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.shutdown())
            return
        if not self._shutdown_complete and self._shutdown_task is None:
            self._shutdown_task = self._track_task(loop.create_task(self.shutdown()))

    def _track_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        """Register a TUI-owned task so shutdown can await or cancel it."""
        self._background_tasks.add(task)

        def consume_done(done: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(done)
            if done.cancelled():
                return
            try:
                done.exception()
            except BaseException:
                # Retrieving the exception prevents asyncio's orphan-task
                # warning; task bodies render their own operational errors.
                pass

        task.add_done_callback(consume_done)
        return task

    # -- 事件 → 渲染 -------------------------------------------------------
    def _event_buffer_flush(self) -> None:
        self._event_buffer.flush()

    def _apply_event(self, event: AgentEvent) -> None:
        ev_type = getattr(event, "type", None)
        if ev_type == EventType.CONFIRMATION_REQUESTED:
            self._show_confirmation(dict(event.payload or {}))
        elif ev_type in (EventType.TURN_END, EventType.RUN_CANCELLED, EventType.ERROR):
            # 终态事件:确认条必然已无意义(abort 时循环随 CancelledError 退出)。
            if self._pending_confirmation is not None:
                self._clear_confirmation()
        self.model.apply(event)
        self._sync_activity_timer()

    def _on_event(self, event: Any) -> None:
        if self._shutdown_complete or self._shutdown_started:
            return
        if getattr(event, "type", None) in {
            EventType.TEXT_DELTA,
            EventType.AGENT_MESSAGE,
            EventType.TOOL_CALL,
            EventType.CONFIRMATION_REQUESTED,
            EventType.TURN_END,
            EventType.ERROR,
            EventType.RUN_CANCELLED,
        }:
            # 停止低频活动动画不需要等待正文归约,避免旧动画任务占用下一轮 loop。
            self._stop_activity_timer()
        self._event_buffer.push(event)
        self._schedule_render()

    async def shutdown(self) -> None:
        """Stop TUI work, release runtime ownership, then leave the backend."""
        if self._shutdown_complete or self._shutdown_started:
            return
        self._shutdown_started = True
        self._accepting_input = False
        self._stop_activity_timer()
        self._render_coordinator.cancel_pending_render()
        self._clear_confirmation()

        tasks = [
            task
            for task in (
                self._restore_task,
                self._conversation_task,
                self._session_action_task,
                self._package_task,
            )
            if task is not None and not task.done()
        ]
        current = asyncio.current_task()
        for task in tuple(self._background_tasks):
            if task is not current and not task.done() and task not in tasks:
                tasks.append(task)
        if self._task_supervisor is not None:
            self._task_supervisor.cancel()
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=1.0
                )
            except asyncio.TimeoutError:
                pass

        if self._unsubscribe is not None:
            unsubscribe, self._unsubscribe = self._unsubscribe, None
            try:
                unsubscribe()
            except (ValueError, KeyError):
                pass

        manager_close = getattr(self._manager, "close", None)
        if callable(manager_close):
            result = manager_close()
            if hasattr(result, "__await__"):
                # The manager owns model/MCP/tool resources. Its async close
                # is the authoritative wait boundary; proceeding after a
                # timeout would allow the TUI to exit while work still holds
                # those resources.
                await result
        elif self._close_runtime is not None:
            result = self._close_runtime()
            if hasattr(result, "__await__"):
                await result

        self._event_buffer.flush()
        width = self._transcript_width()
        self._backend.exit_document(self.model.transcript.iter_lines(width))
        self._shutdown_complete = True

    def _sync_activity_timer(self) -> None:
        self._render_coordinator.sync_activity_timer()

    def _stop_activity_timer(self) -> None:
        self._render_coordinator.stop_activity_timer()

    async def _animate_activity(self) -> None:
        await self._render_coordinator.animate_activity()

    def _schedule_render(self) -> None:
        self._render_coordinator.schedule_render()

    def _flush_render(self) -> None:
        self._render_coordinator.flush_render()

    def _flush_render_now(self) -> None:
        self._render_coordinator.flush_render_now()

    def _transcript_width(self) -> int:
        width, _ = self._backend.transcript_size()
        return width or _DEFAULT_EXIT_WIDTH
