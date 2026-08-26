"""TUI 会话恢复协调器：切换、树、分叉、压缩、重试与过期保护。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from codeagent.app.tui.commands import Command
from codeagent.app.tui.model import TuiModel
from codeagent.app.tui.runtime import phase_label
from codeagent.core.events import AgentEvent, EventType
from codeagent.session.navigation.tree import SessionNode, build_tree


@dataclass(frozen=True)
class RestoreCost:
    message_count: int
    text_chars: int
    tool_output_bytes: int

    @property
    def requires_background(self) -> bool:
        return (
            self.message_count > 1000
            or self.text_chars > 100_000
            or self.tool_output_bytes > 1_000_000
        )


class TuiSessionCoordinator:
    @staticmethod
    def _restore_cost(history: list[Any]) -> RestoreCost:
        text_chars = 0
        tool_output_bytes = 0
        for message in history:
            content = str(getattr(message, "content", "") or "")
            text_chars += len(content)
            if str(getattr(message, "role", "")) == "tool":
                tool_output_bytes += len(content.encode("utf-8"))
        return RestoreCost(len(history), text_chars, tool_output_bytes)

    def _cmd_sessions(self, cmd: Command) -> None:
        # session-resume:无参 = 交互式选择器(↑↓ 选历史会话切换,与 /provider 同款);
        # recent = 快速恢复最近会话;list/new/<id> 为既有语义。
        if not cmd.args:
            self._open_inline_picker("sessions")
            return
        action = cmd.args[0]
        if action == "list":
            refs = self._manager.list()
            if not refs:
                self.model.append_info("(暂无会话)")
                return
            lines = ["会话列表:"]
            # session-tree:父子缩进展示(复用 build_tree;孤儿平级)。
            lines.extend(self._tree_lines(build_tree(refs)))
            self.model.append_info("\n".join(lines))
        elif action == "new":
            session = self._manager.create()
            self._hydrate_current_session()
            self.model.append_info(f"已新建会话: {session.session_id}")
        elif action == "recent":
            # session-resume:快速恢复最近有活动的会话(continue_recent;无会话时新建)。
            session = self._manager.continue_recent()
            self._hydrate_current_session()
            self.model.append_info(f"已恢复最近会话: {session.session_id}")
        else:
            try:
                session = self._manager.switch(action)
            except ValueError as exc:
                self.model.append_info(str(exc))
                return
            self._hydrate_current_session()
            self.model.append_info(f"已切换到会话: {session.session_id}")

    def _cmd_tree(self, cmd: Command) -> None:
        """/tree [session-id]:展示会话 fork 链树;/tree <id> 切换到指定节点。

        - 无参:展示当前会话所在 fork 链树(缩进 + 分支字符,含标题与 id);
        - ``/tree <id>``:切换到该会话(复用 manager.switch,订阅跟随);
        - 会话不存在就地报错;无会话显示空态。
        """
        if cmd.args:
            target = cmd.args[0]
            try:
                session = self._manager.switch(target)
            except ValueError as exc:
                self.model.append_info(str(exc))
                return
            self._hydrate_current_session()
            self.model.append_info(f"已切换到会话: {session.session_id}")
            return
        refs = self._manager.list()
        if not refs:
            self.model.append_info("(暂无会话)")
            return
        lines = ["会话树:"]
        lines.extend(self._tree_lines(build_tree(refs)))
        self.model.append_info("\n".join(lines))

    def _tree_lines(self, roots: list[SessionNode], prefix: str = "") -> list[str]:
        """树节点 → 缩进文本行(分支字符:├─ 中间分支 / └─ 末分支 / │ 延续)。

        复用 build_tree 输出;孤儿(独立根)以未缩进平级展示。
        """
        lines: list[str] = []
        for index, node in enumerate(roots):
            last = index == len(roots) - 1
            branch = "└─ " if last else "├─ "
            title = node.ref.title or node.ref.id
            lines.append(f"{prefix}{branch}{title}  ({node.ref.id})")
            child_prefix = prefix + ("   " if last else "│  ")
            lines.extend(self._tree_lines(node.children, child_prefix))
        return lines

    def _cmd_compact(self, cmd: Command) -> None:
        """/compact:压缩当前会话上下文(异步执行,完成后反馈)。"""
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        if not hasattr(session, "compact"):
            self.model.append_info("/compact 不可用:当前会话不支持压缩")
            return
        self.model.append_info("正在压缩会话上下文...")
        loop = asyncio.get_running_loop()
        loop.create_task(self._run_compact(session))

    def _cmd_output(self, cmd: Command) -> None:
        """分页/导出输出视图；动作只触碰本地显示缓冲。"""
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
        """启动最近一次无副作用模型失败的安全重试。"""
        session = self._manager.current
        failure = getattr(session, "last_failure", None) if session is not None else None
        if not failure or not failure.get("retryable"):
            self.model.append_info("当前失败不可安全重试,请确认副作用后使用 /continue <新消息>")
            return
        loop = asyncio.get_running_loop()
        loop.create_task(self._run_retry(session))

    async def _run_retry(self, session: Any) -> None:
        try:
            await session.retry()
        except ValueError as exc:
            self.model.append_info(str(exc))
        self._schedule_render()

    def _cmd_continue(self, cmd: Command) -> None:
        """失败后执行新的可追踪消息，不复制上一轮工具调用。"""
        if not cmd.args:
            self.model.append_info("用法: /continue <新消息>")
            return
        self._run_conversation(" ".join(cmd.args))

    async def _run_compact(self, session: Any) -> None:
        try:
            compacted = await session.compact()
        except Exception as exc:
            self.model.append_info(str(exc))
            self._schedule_render()
            return
        if compacted:
            self.model.append_info("已压缩:早期轮次已摘要化,上下文已精简")
        else:
            self.model.append_info("上下文较短,无需压缩")
        self._schedule_render()

    def _cmd_fork(self, cmd: Command) -> None:
        """/fork [message-id]:从指定 user 消息分叉会话(缺省最近用户消息)。

        分叉 = 从该消息之前重新开始(对齐 Pi createBranchedSession 语义);
        原会话保留、文件保持当前状态;非法分叉点就地提示。
        """
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        message_id = cmd.args[0] if cmd.args else None
        try:
            forked = self._manager.fork(session.session_id, message_id)
        except ValueError as exc:
            self.model.append_info(str(exc))
            return
        self._hydrate_current_session()
        self.model.append_info(
            f"已分叉会话 {forked.session_id}: "
            f"从消息 {message_id or '(最近用户消息)'} 之前重新开始"
            f"(原会话保留,文件保持当前状态)"
        )


    def _hydrate_current_session(self) -> None:
        """把 current 会话快照装载到 TUI,避免切换后沿用旧 transcript。"""
        self._refresh_skills()
        session = self._manager.current
        if session is None:
            self.model.hydrate_history([])
            self._sync_context_status()
            return
        self.model.apply(
            AgentEvent(
                EventType.RESTORE_STARTED,
                metadata={"session_id": getattr(session, "session_id", None)},
            )
        )
        history = list(getattr(session, "history", []) or [])
        summary = getattr(session, "summary", None)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.model.hydrate_history(history, summary=summary)
        else:
            if self._restore_cost(history).requires_background:
                # 大型恢复的组件构建卸载到线程，完成后校验 session_id，
                # 避免旧会话晚到的快照覆盖当前界面。
                if self._restore_task is not None and not self._restore_task.done():
                    self._restore_task.cancel()
                self._restore_task = loop.create_task(
                    self._restore_large_session(session)
                )
                self._sync_context_status()
                return
            self.model.hydrate_history(history, summary=summary)
        self._sync_context_status()
        self.model.apply(
            AgentEvent(
                EventType.RESTORE_FINISHED,
                metadata={"session_id": getattr(session, "session_id", None)},
            )
        )

    async def _restore_large_session(self, session: Any) -> None:
        """后台构建大型 transcript，过期会话结果只被丢弃。"""
        target_id = getattr(session, "session_id", None)

        def load_snapshot() -> tuple[list[Any], str | None]:
            return (
                list(getattr(session, "history", []) or []),
                getattr(session, "summary", None),
            )

        def build_model(snapshot: tuple[list[Any], str | None]) -> TuiModel:
            history, summary = snapshot
            restored = TuiModel()
            restored.hydrate_history(history, summary)
            return restored

        try:
            snapshot = await asyncio.to_thread(load_snapshot)
            restored = await asyncio.to_thread(build_model, snapshot)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if self._manager.current is session and getattr(session, "session_id", None) == target_id:
                self.model.apply(
                    AgentEvent(
                        EventType.RESTORE_FINISHED,
                        metadata={
                            "session_id": target_id,
                            "success": False,
                            "error_code": "restore_failed",
                            "error_message": str(exc),
                        },
                    )
                )
                self.model.append_info(f"恢复会话失败: {exc}")
                self._schedule_render()
            return
        if (
            self._manager.current is not session
            or getattr(session, "session_id", None) != target_id
        ):
            return
        self.model.transcript = restored.transcript
        self.model._assistant = restored._assistant
        self.model._pending_tools = restored._pending_tools
        self.model._pending_tools_by_id = restored._pending_tools_by_id
        self.model.running = restored.running
        self.model.activity_visible = restored.activity_visible
        self.model.activity_frame = restored.activity_frame
        self._sync_context_status()
        self.model.apply(
            AgentEvent(
                EventType.RESTORE_FINISHED,
                metadata={"session_id": target_id, "message_count": len(snapshot[0])},
            )
        )
        self._schedule_render()

    def _refresh_skills(self) -> None:
        """从组合根重新读取 Package Registry/Adapter 视图(可选注入)。"""
        if self._refresh_skills_callback is None:
            return
        try:
            skills, diagnostics = self._refresh_skills_callback()
        except OSError as exc:
            self._skill_diagnostics = [f"skill_reload_failed: {exc}"]
            return
        self._skills = list(skills)
        self._skill_diagnostics = list(diagnostics)
        self._skills_by_name = {skill.name: skill for skill in self._skills}

    def _sync_context_status(self) -> None:
        """把当前会话最近一次输入 token 与窗口上限同步到 footer。"""
        session = self._manager.current
        if session is None:
            self.model.status.context_tokens = None
            self.model.status.context_window = None
            self.model.set_context_status(None, None)
            return
        tokens = getattr(session, "context_tokens", None)
        window = getattr(session, "context_window", None)
        self.model.status.context_tokens = tokens
        self.model.status.context_window = window
        self.model.set_context_status(tokens, window)
