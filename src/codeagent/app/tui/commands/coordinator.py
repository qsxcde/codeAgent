"""TUI 通用命令分派与配置切换协作者。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from codeagent.app.tasks.modes import TaskMode
from .skills import TuiSkillCommandCoordinator
from .status import TuiStatusCommandCoordinator
from .parser import Command, help_text
from .interaction import _COMMANDS


class TuiCommandCoordinator(TuiStatusCommandCoordinator, TuiSkillCommandCoordinator):
    """分派非会话命令；状态和技能由专门协作者处理。"""

    def _cmd_help(self, cmd: Command) -> None:
        self.model.append_info(help_text(_COMMANDS))

    def _cmd_ask(self, cmd: Command) -> None:
        self._run_with_explicit_mode(cmd, TaskMode.ASK)

    def _cmd_plan(self, cmd: Command) -> None:
        self._run_with_explicit_mode(cmd, TaskMode.PLAN)

    def _cmd_code(self, cmd: Command) -> None:
        self._run_with_explicit_mode(cmd, TaskMode.CODE)

    def _run_with_explicit_mode(self, cmd: Command, mode: TaskMode) -> None:
        if not cmd.args:
            self.model.append_info(f"用法: /{mode.value} <消息>")
            return
        self._run_conversation(" ".join(cmd.args), mode=mode)

    def _cmd_mode(self, cmd: Command) -> None:
        if not cmd.args:
            self.model.append_info(f"当前模式: {self._task_mode.value}")
            return
        try:
            self._task_mode = TaskMode(cmd.args[0].lower())
        except ValueError:
            self.model.append_info("未知模式；可选 ask、plan、code、auto")
            return
        self.model.status.mode = self._task_mode.value
        self.model.append_info(f"已切换到 {self._task_mode.value} 模式")

    def _cmd_clear(self, cmd: Command) -> None:
        self.model.transcript.clear()

    def _cmd_mcp(self, cmd: Command) -> None:
        grouped: dict[str, list[str]] = {}
        for tool in self._manager.tools:
            name = getattr(tool, "name", "")
            if name.startswith("mcp__"):
                _, server, tool_name = (*name.split("__", 2), "?")[:3]
                grouped.setdefault(server, []).append(tool_name)
        if not grouped and not self._mcp_diagnostics:
            self.model.append_info("MCP: (未配置 server)")
            return
        lines = ["MCP server:"]
        lines.extend(f"  {server}: {', '.join(sorted(tools))}" for server, tools in sorted(grouped.items()))
        if not grouped:
            lines.append("  (无已连接 server)")
        if self._mcp_diagnostics:
            lines.extend(["诊断:", *(f"  {message}" for message in self._mcp_diagnostics)])
        self.model.append_info("\n".join(lines))

    def _cmd_tools(self, cmd: Command) -> None:
        names = [getattr(tool, "name", "") for tool in self._manager.tools]
        self.model.append_info("可用工具: " + ", ".join(name for name in names if name) if any(names) else "可用工具: (无)")

    def _cmd_provider(self, cmd: Command) -> None:
        self._select_or_apply_config(cmd, "provider")

    def _cmd_model(self, cmd: Command) -> None:
        self._select_or_apply_config(cmd, "model")

    def _cmd_effort(self, cmd: Command) -> None:
        self._select_or_apply_config(cmd, "effort")

    def _select_or_apply_config(self, cmd: Command, field: str) -> None:
        if not cmd.args:
            self._open_inline_picker(field)
            return
        self._apply_config(**{field: cmd.args[0]})

    def _cmd_login(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("login")
            return
        provider = cmd.args[0]
        if provider not in self._picker_candidates("login"):
            self.model.append_info(f"未知 provider: {provider}")
            return
        self._begin_login(provider)

    def _begin_login(self, provider: str) -> None:
        if provider == "fake":
            self.model.append_info("fake 无需密钥")
            self._schedule_render()
            return
        self._login_pending, self._suggestions = provider, []
        self._backend.set_suggestions([])
        self._backend.set_input_mask(True)
        self._backend.set_input_placeholder(f"输入 {provider.upper()}_API_KEY,Enter 保存 / Esc 取消")
        self.model.append_info(f"/login {provider}:请输入 API key(输入将隐藏)")
        self._schedule_render()

    def _end_login(self) -> None:
        self._login_pending = None
        self._backend.set_input_mask(False)

    def _apply_config(self, *, provider: str | None = None, model: str | None = None, effort: str | None = None) -> bool:
        if self._rebuild_ports is None:
            self.model.append_info("当前环境不支持热切换(未注入端口重建器)")
            return False
        try:
            self._pending_provider = provider if provider is not None else self._provider
            result = (self._rebuild_ports_async or self._rebuild_ports)(provider, model, effort)
            if inspect.isawaitable(result):
                self._track_task(asyncio.get_running_loop().create_task(self._finish_async_config(result)))
                self.model.append_info("正在等待当前运行收尾并切换配置...")
                self._schedule_render()
                return True
            new_model, new_effort = result
        except ValueError as exc:
            self.model.append_info(str(exc))
            return False
        self._finish_config(new_model, new_effort)
        return True

    async def _finish_async_config(self, result: Any) -> None:
        try:
            self._finish_config(*(await result))
        except ValueError as exc:
            self.model.append_info(str(exc))
        self._schedule_render()

    def _finish_config(self, model: str, effort: str) -> None:
        self.model.status.model, self.model.status.effort = model, effort
        provider = getattr(self, "_pending_provider", self._provider)
        self._provider = provider or self._provider
        self._refresh_model_capabilities(self._provider, model, effort)
        self._refresh_skills()
        self.model.append_info("已切换配置")

    def _refresh_model_capabilities(
        self, provider: str | None, model: str, effort: str
    ) -> None:
        resolver = getattr(self, "_resolve_model_capabilities", None)
        if callable(resolver):
            self.model.status.model_capabilities = resolver(provider, model, effort)
