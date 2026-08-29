"""TUI 命令的状态、诊断与用量展示协作者。"""

from __future__ import annotations

from typing import Any

from codeagent.app.context_diagnostics import format_context_diagnostics
from codeagent.core.context.diagnostics import ContextDiagnostics

from .parser import Command
from .model_capabilities import append_model_capability_lines
from ..state.runtime import phase_label


class TuiStatusCommandCoordinator:
    """只负责把应用状态投影为 `/status` 文本。"""

    def _cmd_status(self, cmd: Command) -> None:
        session = self._manager.current
        runtime = self.model.runtime
        model = self.model.status.model or "(未配置)"
        effort = self.model.status.effort or ""
        lines = [
            f"会话: {session.session_id if session is not None else '(无会话)'}",
            f"状态: {phase_label(runtime.phase)}",
            f"模式: {self._task_mode.value}",
            f"模型: {model} {effort}".rstrip(),
        ]
        if self.model.status.task_phase:
            lines.append(
                f"任务: {self.model.status.task_phase}"
                f" {self.model.status.task_command or self.model.status.task_message}".rstrip()
            )
        append_model_capability_lines(
            lines, getattr(self.model.status, "model_capabilities", None), session
        )
        self._append_runtime_lines(lines, runtime)
        self._append_tool_capability_lines(lines)
        self._append_context_lines(lines)
        lines.append(f"用量: {self._usage_line(session)}")
        self.model.append_info("\n".join(lines))

    def _cmd_context(self, cmd: Command) -> None:
        """Show the complete read-only context diagnostics block."""
        session = self._manager.current
        diagnostics = getattr(session, "context_diagnostics", None)
        if not isinstance(diagnostics, ContextDiagnostics):
            diagnostics = self.model.context_diagnostics
        self.model.append_info("\n".join(format_context_diagnostics(diagnostics)))

    def _append_runtime_lines(self, lines: list[str], runtime: Any) -> None:
        render, output = self.model.render_stats, self.model.output_stats
        if runtime.phase == "idle" and not runtime.error_code:
            lines.append(
                f"诊断: 阶段 空闲 · 渲染 {int(render.get('frames', 0))} 帧 · "
                f"输出 {output.get('results', 0)} 个"
            )
            return
        lines.extend(
            [
                f"阶段: {phase_label(runtime.phase)} · {runtime.elapsed_ms / 1000:.1f}s",
                f"当前操作: {runtime.current_operation or '(无)'}",
                f"工具: {runtime.tool_counts or '(无)'}",
            ]
        )
        if runtime.error_code:
            lines.extend(
                [
                    f"错误码: {runtime.error_code}",
                    f"错误: {runtime.error_message or '(无详情)'}",
                    f"可重试: {'是' if runtime.retryable else '否'}",
                    f"清理状态: {'不确定' if runtime.cleanup_uncertain else runtime.side_effect_state}",
                ]
            )
        lines.extend(
            [
                "渲染: 帧 {frames} · 缓存命中 {hits} · 最近 {last:.1f}ms".format(
                    frames=int(render.get("frames", 0)),
                    hits=int(render.get("cache_hits", 0)),
                    last=float(render.get("last_render_ms", 0.0)),
                ),
                "输出: {results} 个结果 · {bytes} B · {lines} 行 · 截断 {truncated}".format(
                    results=output.get("results", 0),
                    bytes=output.get("bytes", 0),
                    lines=output.get("lines", 0),
                    truncated=output.get("truncated", 0),
                ),
            ]
        )

    def _append_context_lines(self, lines: list[str]) -> None:
        if self._agents_sources:
            lines.extend(["上下文文件:", *(f"  {source}" for source in self._agents_sources)])
        else:
            lines.append("上下文文件: (无)")
        if self._skills:
            lines.append("技能:")
            self._append_skill_lines(lines)
        else:
            lines.append("技能: (无)")
        if self._skill_diagnostics:
            lines.extend(["技能诊断:", *(f"  {message}" for message in self._skill_diagnostics)])
        if self._mcp_diagnostics:
            lines.extend(["MCP:", *(f"  {message}" for message in self._mcp_diagnostics)])

    def _append_tool_capability_lines(self, lines: list[str]) -> None:
        capabilities = getattr(self._manager, "tool_capabilities", None)
        if capabilities is None:
            return
        labels = {
            "platform": "平台",
            "shell": "Shell",
            "process_tree_cleanup": "进程清理",
            "rg": "rg",
            "fd": "fd",
            "permissions": "权限策略",
        }
        lines.append("工具能力:")
        for item in capabilities:
            state = "可用" if item.available else "不可用"
            label = labels.get(item.key, item.key)
            detail = f" · {item.detail}" if item.detail else ""
            lines.append(f"  {label}: {state} · {item.code} · {item.message}{detail}")

    def _append_skill_lines(self, lines: list[str]) -> None:
        bootstrap = next((skill for skill in self._skills if skill.bootstrap), None)
        if bootstrap is not None:
            from codeagent.app.skills.runtime import CodeAgentAdapter

            adapter = CodeAgentAdapter()
            lines.extend([f"  Bootstrap: {bootstrap.name}", f"  Adapter: {adapter.version}"])
            missing = [name for name, enabled in adapter.capabilities().items() if not enabled]
            if missing:
                lines.append(f"  未提供能力: {', '.join(missing)}")
        if any(skill.package_id for skill in self._skills):
            lines.append("  Package 扩展: 未执行第三方插件代码")
        for skill in self._skills:
            lines.append(f"  {skill.name} — {skill.description}")
            if skill.package_id:
                version, scope = skill.package_version or "unversioned", skill.package_scope or "unknown"
                lines.append(f"    Package: {skill.package_id}@{version} ({scope})")

    @staticmethod
    def _usage_line(session: Any | None) -> str:
        if session is None:
            return "(无)"
        usage = session.usage
        if not (usage.input_tokens or usage.output_tokens):
            return "(无)"
        cached = usage.cached_tokens
        hit = (
            f" · 缓存命中约 {min(100.0, cached / usage.input_tokens * 100.0):.1f}% "
            f"({cached}/{usage.input_tokens})"
            if usage.input_tokens > 0 and cached > 0
            else ""
        )
        return f"输入 {usage.input_tokens} · 输出 {usage.output_tokens + usage.reasoning_tokens}{hit}"
