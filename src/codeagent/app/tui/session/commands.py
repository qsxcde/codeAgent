"""会话列表、树和基础切换命令。"""

from __future__ import annotations

from typing import Any

from ..commands.parser import Command
from codeagent.session.navigation.tree import SessionNode, build_tree


class SessionCommandsMixin:
    def _cmd_sessions(self, cmd: Command) -> None:
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
            lines.extend(self._tree_lines(build_tree(refs)))
            self.model.append_info("\n".join(lines))
        elif action == "new":
            if self._schedule_session_action(
                "create_async", lambda session: f"已新建会话: {session.session_id}"
            ):
                return
            session = self._manager.create()
            self._hydrate_current_session()
            self.model.append_info(f"已新建会话: {session.session_id}")
        elif action == "recent":
            if self._schedule_session_action(
                "continue_recent_async", lambda session: f"已恢复最近会话: {session.session_id}"
            ):
                return
            session = self._manager.continue_recent()
            self._hydrate_current_session()
            self.model.append_info(f"已恢复最近会话: {session.session_id}")
        else:
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
