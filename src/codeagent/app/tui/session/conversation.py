"""TUI 对话任务与确认协调器：任务生命周期、确认、打断与任务状态。"""

from __future__ import annotations

import asyncio
from typing import Any

from codeagent.app.errors.reporting import report_unexpected_error
from codeagent.app.tasks.modes import TaskMode
from codeagent.app.tasks.supervisor import TaskEvent, TaskPhase, TaskSupervisor
from ..commands.parser import Command
from ..presentation.primitives import Span
from ..presentation.theme import ACCENT, DIM, ERROR, WARNING
from codeagent.core.contracts.events import AgentEvent, EventType


class TuiConversationCoordinator:
    def _on_confirmation_response(self, approved: bool) -> None:
        """确认条 y/n 响应:反馈会话确认队列并收起确认条。

        请求 id 匹配在会话层(``respond_approval`` 按 id 匹配,过期响应丢弃),
        视图只负责把当前待确认请求的 id 与用户选择一并送出。
        """
        if self._pending_confirmation is None:
            return
        pending_id = str(self._pending_confirmation.get("request_id") or "")
        self._clear_confirmation()
        if not pending_id:
            return
        session = self._manager.current
        if session is not None and hasattr(session, "respond_approval"):
            session.respond_approval(pending_id, approved)

    def _show_confirmation(self, payload: dict[str, Any]) -> None:
        """显示确认条(工具摘要 + 原因 + 键位提示),激活后端 y/n 键。"""
        self._pending_confirmation = payload
        tool = str(payload.get("tool") or "?")
        summary = str(payload.get("summary") or "")
        reason = str(payload.get("reason") or "")
        lines: list[list[Span]] = [
            [Span("⚠ 需要确认 ", fg=WARNING)],
            [Span(f"  {tool}: {summary}", fg=ACCENT)],
            [Span(f"  原因: {reason}", fg=DIM)],
            [Span("  [y] 允许  [n] 拒绝  [Esc] 拒绝并中止", fg=ERROR)],
        ]
        self._backend.set_confirmation(lines)

    def _clear_confirmation(self) -> None:
        """收起确认条并解除后端 y/n 键激活。"""
        self._pending_confirmation = None
        self._backend.set_confirmation(None)


    def _interrupt(self) -> None:
        """Esc:登录态取消 → 浮层收起 → 运行中打断 → 空闲提示退出方式。

        退出键位已拆分为 Ctrl+C / Ctrl+Q(见 ``_quit``)。
        """
        if self._login_pending is not None:
            # 密钥输入态:Esc 取消,不写入任何内容(登录态无建议浮层)。
            self._end_login()
            self.model.append_info("已取消密钥输入")
            self._schedule_render()
            return
        if self._suggestions and not self.model.running:
            # 选择浮层激活:Esc 仅收起(值语境 = 取消选择,连同输入清空)。
            self._suggestions = []
            self._backend.set_suggestions([])
            if self._suggestion_kind == "value":
                self._suppress_next_suggestions = True
                self._backend.set_input_text("")
            return
        if self._task_active and self._task_supervisor is not None:
            self._task_supervisor.cancel()
            self.model.append_info("正在取消当前任务")
            self._schedule_render()
        elif self.model.running:
            session = self._manager.current
            if session is not None:
                session.abort()
            self._schedule_render()
        else:
            self.model.append_info("按 Ctrl+C 退出")


    def _cmd_quit(self, cmd: Command) -> None:
        """/quit:退出 TUI(等同 Ctrl+C——运行中先中止当前轮,再打印完整文档)。"""
        self._quit()

    def _quit(self) -> None:
        """Ctrl+C / Ctrl+Q:退出——运行中先中止当前轮(未完成轮次不落盘,
        既有回滚语义),再打印完整文档退出。"""
        if self._task_active and self._task_supervisor is not None:
            self._task_supervisor.cancel()
        elif self.model.running:
            session = self._manager.current
            if session is not None:
                session.abort()
        self._exit()


    def _on_task_event(self, event: TaskEvent) -> None:
        """把任务级状态写入状态栏；完整诊断仍由监督器结果负责。"""
        self.model.status.set_task_status(
            event.phase.value,
            command=event.command,
            attempt=event.attempt,
            max_attempts=event.max_attempts,
            message=event.message,
        )
        if event.phase in {
            TaskPhase.COMPLETED,
            TaskPhase.UNVERIFIED,
            TaskPhase.FAILED,
            TaskPhase.CANCELLED,
            TaskPhase.NO_CHANGES,
        }:
            self._task_active = False
        self._schedule_render()


    def _run_conversation(self, text: str, *, mode: TaskMode | None = None) -> None:
        """在当前会话发起一轮任务；验证只由工作区变更触发。"""
        session = self._manager.current
        if session is None:
            return
        selected_mode = mode or self._task_mode
        self._task_active = True
        self.model.append_pending_user(text)
        try:
            self._flush_render_now()
            supervisor = TaskSupervisor(
                session,
                cwd=self.model.status.cwd or ".",
                base_policy=getattr(session, "policy", None),
                event_sink=self._on_task_event,
            )
        except Exception as exc:
            self.model.clear_pending_user(text)
            self._task_active = False
            self.model.apply(
                AgentEvent(
                    EventType.ERROR,
                    payload=report_unexpected_error("任务启动", exc),
                    metadata={"error_code": "tui_task_start_error"},
                )
            )
            self._schedule_render()
            return
        self._task_supervisor = supervisor

        async def _run() -> None:
            try:
                await supervisor.run(text, mode=selected_mode)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A failure outside AgentSession (workspace inspection,
                # verification resolution, or a coordinator bug) must still
                # become visible in the transcript instead of an orphaned
                # "Task exception was never retrieved" warning.
                self.model.apply(
                    AgentEvent(
                        EventType.ERROR,
                        payload=report_unexpected_error("任务执行", exc),
                        metadata={"error_code": "tui_task_error"},
                    )
                )
            finally:
                self.model.clear_pending_user(text)
                if self._task_supervisor is supervisor:
                    self._task_active = False
                    self._task_supervisor = None
                self._schedule_render()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_run())
            return
        self._conversation_task = self._track_task(loop.create_task(_run()))
