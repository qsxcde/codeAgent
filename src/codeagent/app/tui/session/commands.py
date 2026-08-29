"""会话列表、树和基础切换命令。"""

from __future__ import annotations

import shlex

from ..commands.parser import Command
from codeagent.session.navigation.tree import SessionNode, build_tree
from codeagent.session.persistence import SessionQuery


class SessionCommandsMixin:
    def _cmd_name(self, cmd: Command) -> None:
        current = self._manager.current
        if current is None:
            self.model.append_info("无法设置会话标题: 当前没有会话")
            return
        if not cmd.args and cmd.has_argument_separator:
            self.model.append_info("设置会话标题失败: 标题不能为空")
            return
        if not cmd.args:
            title = next(
                (
                    ref.title
                    for ref in self._manager.list()
                    if ref.id == current.session_id
                ),
                "",
            )
            self.model.append_info(
                f"当前会话标题: {title or '(无标题)'}\n用法: /name <title>"
            )
            return
        try:
            title = self._manager.rename(current.session_id, " ".join(cmd.args))
        except (OSError, ValueError) as exc:
            self.model.append_info(f"设置会话标题失败: {exc}")
            return
        self.model.append_info(f"已设置会话标题: {title}")

    def _cmd_sessions(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("sessions")
            return
        action = cmd.args[0]
        if action == "search":
            self._cmd_session_search(cmd)
        elif action == "filter":
            self._cmd_session_filter(cmd)
        elif action == "archived":
            self._show_session_query(SessionQuery(archived=True), "归档会话")
        elif action in {"archive", "unarchive"}:
            self._cmd_session_archive(cmd, action)
        elif action == "delete":
            self._cmd_session_delete(cmd)
        else:
            self._cmd_sessions_legacy(cmd, action)

    def _cmd_session_search(self, cmd: Command) -> None:
        if len(cmd.args) < 2:
            self.model.append_info("用法: /sessions search <text>")
            return
        self._show_session_query(SessionQuery(text=" ".join(cmd.args[1:])), "搜索结果")

    def _cmd_session_filter(self, cmd: Command) -> None:
        try:
            query = self._parse_session_filter(cmd.raw_args)
        except (TypeError, ValueError) as exc:
            self.model.append_info(f"筛选失败: {exc}")
            return
        self._show_session_query(query, "筛选结果")

    def _cmd_session_archive(self, cmd: Command, action: str) -> None:
        session_ids = list(cmd.args[1:])
        if not session_ids:
            self.model.append_info(f"用法: /sessions {action} <id...>")
            return
        try:
            results = getattr(self._manager, f"{action}_many")(session_ids)
        except (OSError, ValueError) as exc:
            self.model.append_info(f"{action}失败: {exc}")
            return
        self._show_session_mutation(results, action)

    def _cmd_session_delete(self, cmd: Command) -> None:
        session_ids = list(cmd.args[1:])
        if not session_ids or session_ids[-1].casefold() != "confirm":
            self.model.append_info(
                "删除失败: 需要确认; 用法: /sessions delete <id...> confirm"
            )
            return
        session_ids.pop()
        try:
            results = self._manager.delete_many(session_ids, confirmed=True)
        except (OSError, ValueError) as exc:
            self.model.append_info(f"删除失败: {exc}")
            return
        self._show_session_mutation(results, "delete")

    def _cmd_sessions_legacy(self, cmd: Command, action: str) -> None:
        if action == "list":
            refs = self._manager.list()
            if not refs:
                self.model.append_info("(暂无会话)")
                return
            lines = ["会话列表:"]
            lines.extend(self._tree_lines(build_tree(refs)))
            self.model.append_info("\n".join(lines))
            return
        if action == "new":
            if self._schedule_session_action(
                "create_async", lambda session: f"已新建会话: {session.session_id}"
            ):
                return
            session = self._manager.create()
            self._hydrate_current_session()
            self.model.append_info(f"已新建会话: {session.session_id}")
            return
        if action == "recent":
            if self._schedule_session_action(
                "continue_recent_async", lambda session: f"已恢复最近会话: {session.session_id}"
            ):
                return
            session = self._manager.continue_recent()
            self._hydrate_current_session()
            self.model.append_info(f"已恢复最近会话: {session.session_id}")
            return
        if self._schedule_session_action(
            "switch_async", lambda session: f"已切换到会话: {session.session_id}", action
        ):
            return
        try:
            session = self._manager.switch(action)
        except ValueError as exc:
            self.model.append_info(str(exc))
            return
        self._hydrate_current_session()
        self.model.append_info(f"已切换到会话: {session.session_id}")

    @staticmethod
    def _parse_session_filter(raw_args: str) -> SessionQuery:
        """Parse ``key=value`` filters while preserving quoted values."""
        try:
            parts = shlex.split(raw_args, comments=False, posix=True)
        except ValueError as exc:
            raise ValueError(f"筛选语法无效: {exc}") from exc
        if len(parts) < 2 or parts[0] != "filter":
            raise ValueError("用法: /sessions filter key=value...")
        values: dict[str, str] = {}
        allowed = {"title", "model", "status", "after", "before"}
        for part in parts[1:]:
            key, separator, value = part.partition("=")
            key = key.casefold()
            if not separator or key not in allowed or not value:
                raise ValueError(
                    "筛选项必须是 title/model/status/after/before=值"
                )
            if key in values:
                raise ValueError(f"筛选项重复: {key}")
            values[key] = value
        return SessionQuery(
            text=values.get("title", ""),
            model=values.get("model", ""),
            after=values.get("after", ""),
            before=values.get("before", ""),
            status=values.get("status", ""),
        )

    def _show_session_query(self, query: SessionQuery, label: str) -> None:
        refs = self._manager.list(query)
        if not refs:
            self.model.append_info(f"{label}: 无匹配会话")
            return
        lines = [f"{label} ({len(refs)}):"]
        for ref in refs:
            title = ref.title or "(无标题)"
            model = ref.model or "(未设置模型)"
            activity = ref.last_activity_at or ref.timestamp or "(未知)"
            status = getattr(ref, "status", "idle")
            lines.append(f"- {title} | {model} | {activity} | {status} | {ref.id}")
        self.model.append_info("\n".join(lines))

    def _show_session_mutation(self, results: dict[str, str], action: str) -> None:
        success_state = {
            "archive": "archived",
            "unarchive": "unarchived",
            "delete": "deleted",
        }[action]
        success = [sid for sid, state in results.items() if state == success_state]
        failed = [(sid, state) for sid, state in results.items() if state != success_state]
        label = {"archive": "归档", "unarchive": "取消归档", "delete": "删除"}[action]
        lines = [f"已{label} {len(success)} 个会话"]
        if success:
            lines.append("成功: " + ", ".join(success))
        if failed:
            lines.extend(f"失败: {sid} ({state})" for sid, state in failed)
        self.model.append_info("\n".join(lines))

    def _cmd_tree(self, cmd: Command) -> None:
        if cmd.args:
            target = cmd.args[0]
            if self._schedule_session_action(
                "switch_async", lambda session: f"已切换到会话: {session.session_id}", target
            ):
                return
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
        lines: list[str] = []
        for index, node in enumerate(roots):
            last = index == len(roots) - 1
            branch = "└─ " if last else "├─ "
            title = node.ref.title or node.ref.id
            lines.append(f"{prefix}{branch}{title}  ({node.ref.id})")
            child_prefix = prefix + ("   " if last else "│  ")
            lines.extend(self._tree_lines(node.children, child_prefix))
        return lines
