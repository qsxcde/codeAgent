"""会话压缩、重试、导出和分叉命令。"""

from __future__ import annotations

import asyncio
from typing import Any

from codeagent.app.errors.reporting import report_unexpected_error
from ..commands.parser import Command


class SessionActionsMixin:
    def _cmd_compact(self, cmd: Command) -> None:
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        if not hasattr(session, "compact"):
            self.model.append_info("/compact 不可用:当前会话不支持压缩")
            return
        self.model.append_info("正在压缩会话上下文...")
        loop = asyncio.get_running_loop()
        self._track_task(loop.create_task(self._run_compact(session)))

    def _cmd_output(self, cmd: Command) -> None:
        action = cmd.args[0] if cmd.args else "status"
        call_id = cmd.args[1] if len(cmd.args) >= 2 else None
        if action in {"next", "prev", "previous"}:
            delta = 1 if action == "next" else -1
            if not self.model.page_output(delta, call_id):
                self.model.append_info("没有更多输出页")
            return
        if action == "export":
            if len(cmd.args) < 2:
                self.model.append_info("用法: /output export <path> [tool-call-id]")
                return
            path = cmd.args[1]
            call_id = cmd.args[2] if len(cmd.args) >= 3 else None
            try:
                exported = self.model.export_output(path, call_id)
            except (OSError, ValueError) as exc:
                self.model.append_info(f"输出导出失败: {exc}")
            else:
                self.model.append_info(f"已导出工具输出: {exported}")
            return
        self.model.append_info("用法: /output next|prev | /output export <path> [tool-call-id]")

    def _cmd_retry(self, cmd: Command) -> None:
        session = self._manager.current
        failure = getattr(session, "last_failure", None) if session is not None else None
        if not failure or not failure.get("retryable"):
            self.model.append_info("当前失败不可安全重试,请确认副作用后使用 /continue <新消息>")
            return
        loop = asyncio.get_running_loop()
        self._track_task(loop.create_task(self._run_retry(session)))

    async def _run_retry(self, session: Any) -> None:
        try:
            await session.retry()
        except ValueError as exc:
            self.model.append_info(str(exc))
        except Exception as exc:
            self.model.append_info(report_unexpected_error("重试", exc))
        self._schedule_render()

    def _cmd_continue(self, cmd: Command) -> None:
        if not cmd.args:
            self.model.append_info("用法: /continue <新消息>")
            return
        self._run_conversation(" ".join(cmd.args))

    async def _run_compact(self, session: Any) -> None:
        try:
            compacted = await session.compact()
        except Exception as exc:
            self.model.append_info(report_unexpected_error("压缩上下文", exc))
            self._schedule_render()
            return
        if compacted:
            self.model.append_info("已压缩:早期轮次已摘要化,上下文已精简")
        else:
            self.model.append_info("上下文较短,无需压缩")
        self._schedule_render()

    def _cmd_fork(self, cmd: Command) -> None:
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        message_id = cmd.args[0] if cmd.args else None
        if self._schedule_session_action(
            "fork_async",
            lambda forked: (
                f"已分叉会话 {forked.session_id}: 从消息 {message_id or '(最近用户消息)'} 之前重新开始"
                "(原会话保留,文件保持当前状态)"
            ),
            session.session_id,
            message_id,
        ):
            return
        try:
            forked = self._manager.fork(session.session_id, message_id)
        except ValueError as exc:
            self.model.append_info(str(exc))
            return
        self._hydrate_current_session()
        self.model.append_info(
            f"已分叉会话 {forked.session_id}: 从消息 {message_id or '(最近用户消息)'} 之前重新开始"
            "(原会话保留,文件保持当前状态)"
        )
