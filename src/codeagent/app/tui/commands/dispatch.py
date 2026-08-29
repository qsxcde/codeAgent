"""TUI 斜杠命令分派及异常隔离。"""

from __future__ import annotations

from codeagent.app.errors.reporting import report_unexpected_error
from .parser import Command


class TuiCommandDispatcher:
    def _dispatch_command(self, cmd: Command) -> None:
        handler = {
            "help": self._cmd_help, "ask": self._cmd_ask, "plan": self._cmd_plan,
            "code": self._cmd_code, "mode": self._cmd_mode, "clear": self._cmd_clear,
            "status": self._cmd_status, "context": self._cmd_context,
            "tools": self._cmd_tools, "sessions": self._cmd_sessions,
            "tree": self._cmd_tree, "fork": self._cmd_fork, "compact": self._cmd_compact,
            "output": self._cmd_output, "retry": self._cmd_retry, "continue": self._cmd_continue,
            "skills": self._cmd_skills, "mcp": self._cmd_mcp, "provider": self._cmd_provider,
            "login": self._cmd_login, "model": self._cmd_model, "effort": self._cmd_effort,
            "quit": self._cmd_quit,
        }.get(cmd.name)
        if handler is None:
            self.model.append_info(f"未知命令: /{cmd.name}")
        else:
            try:
                handler(cmd)
            except Exception as exc:
                self.model.append_info(report_unexpected_error("命令执行", exc))
        self._schedule_render()
