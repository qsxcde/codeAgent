"""TUI 斜杠命令协调器：命令处理、技能/MCP 展示与配置切换。"""

from __future__ import annotations

import asyncio
from typing import Any

from codeagent.app.skills import Skill, format_skill_invocation
from codeagent.app.task_modes import TaskMode
from codeagent.app.tui.commands import Command, help_text
from codeagent.app.tui.interaction import _COMMANDS
from codeagent.app.tui.runtime import phase_label


class TuiCommandCoordinator:
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

    def _cmd_status(self, cmd: Command) -> None:
        session = self._manager.current
        session_id = session.session_id if session is not None else "(无会话)"
        runtime = self.model.runtime
        state = phase_label(runtime.phase)
        model = self.model.status.model or "(未配置)"
        effort = self.model.status.effort or ""
        lines = [
            f"会话: {session_id}",
            f"状态: {state}",
            f"模式: {self._task_mode.value}",
            f"模型: {model} {effort}".rstrip(),
        ]
        if self.model.status.task_phase:
            lines.append(
                f"任务: {self.model.status.task_phase}"
                f" {self.model.status.task_command or self.model.status.task_message}".rstrip()
            )
        render = self.model.render_stats
        output = self.model.output_stats
        if runtime.phase != "idle" or runtime.error_code:
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
        else:
            lines.append(
                f"诊断: 阶段 空闲 · 渲染 {int(render.get('frames', 0))} 帧 · "
                f"输出 {output.get('results', 0)} 个"
            )
        # 分层上下文文件来源(agents-md-hierarchy:加载结果可见可断言)。
        if self._agents_sources:
            lines.append("上下文文件:")
            lines.extend(f"  {source}" for source in self._agents_sources)
        else:
            lines.append("上下文文件: (无)")
        # 已加载技能与诊断(skills-system:加载结果可见可断言)。
        if self._skills:
            lines.append("技能:")
            bootstrap = next((skill for skill in self._skills if skill.bootstrap), None)
            if bootstrap is not None:
                lines.append(f"  Bootstrap: {bootstrap.name}")
                from codeagent.app.skill_runtime import CodeAgentAdapter

                adapter = CodeAgentAdapter()
                lines.append(f"  Adapter: {adapter.version}")
                missing = [name for name, enabled in adapter.capabilities().items() if not enabled]
                if missing:
                    lines.append(f"  未提供能力: {', '.join(missing)}")
            if any(skill.package_id for skill in self._skills):
                lines.append("  Package 扩展: 未执行第三方插件代码")
            for skill in self._skills:
                lines.append(f"  {skill.name} — {skill.description}")
                if skill.package_id:
                    version = skill.package_version or "unversioned"
                    scope = skill.package_scope or "unknown"
                    lines.append(f"    Package: {skill.package_id}@{version} ({scope})")
        else:
            lines.append("技能: (无)")
        if self._skill_diagnostics:
            lines.append("技能诊断:")
            lines.extend(f"  {message}" for message in self._skill_diagnostics)
        # MCP 装配诊断(mcp-client:server 失败/工具裁剪,加载结果可见可断言)。
        if self._mcp_diagnostics:
            lines.append("MCP:")
            lines.extend(f"  {message}" for message in self._mcp_diagnostics)
        # 用量(cost-transparency:会话累计 input/output(含推理)/缓存命中率)。
        lines.append(f"用量: {self._usage_line(session)}")
        self.model.append_info("\n".join(lines))

    def _usage_line(self, session: Any | None) -> str:
        """格式化会话累计用量行(cost-transparency)。

        - 无会话 / 无 store / 全零 → 空态「(无)」;
        - 输出 = output + reasoning(展示层并入);
        - 缓存命中率 ≈ cached / input,钳制 0~100%,标注「约」。
        """
        if session is None:
            return "(无)"
        usage = session.usage
        if not (usage.input_tokens or usage.output_tokens):
            return "(无)"
        input_k = usage.input_tokens
        output = usage.output_tokens + usage.reasoning_tokens
        cached = usage.cached_tokens
        if input_k > 0 and cached > 0:
            ratio = min(100.0, cached / input_k * 100.0)
            hit = f" · 缓存命中约 {ratio:.1f}% ({cached}/{input_k})"
        else:
            hit = ""
        return f"输入 {input_k} · 输出 {output}{hit}"

    @staticmethod
    def _skill_status_line(skill: Skill) -> str:
        """技能状态行:直接目录保持旧格式,Package 增加来源元数据。"""
        line = f"{skill.name} — {skill.description}"
        if skill.package_id:
            version = skill.package_version or "unversioned"
            scope = skill.package_scope or "unknown"
            line += f" (Package: {skill.package_id}@{version} ({scope}))"
        return line

    def _cmd_skills(self, cmd: Command) -> None:
        """/skills:紧凑列出、查看详情或手动加载 Skill。

        手动加载是用户显式触发(提示词表达不出时的确定性出口):渲染块以
        标注技能名的 user 消息进入会话,模型收到后直接执行——不依赖模型
        自主调用 skill 工具(design skills-system §3)。
        """
        if not cmd.args:
            if not self._skills:
                self.model.append_info("技能: (无)")
                return
            self.model.append_info(self._compact_skills_text())
            return
        if cmd.args[0] == "info":
            self._cmd_skill_info(cmd.args[1:])
            return
        if cmd.args[0] in {"install", "list", "update", "remove", "reload"}:
            self._cmd_skill_package(cmd.args[0], cmd.args[1:])
            return
        name = cmd.args[0]
        skill = self._skills_by_name.get(name)
        if skill is None:
            names = ", ".join(s.name for s in self._skills) or "(无)"
            self.model.append_info(f"未知技能: {name}(可用: {names})")
            return
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        block = format_skill_invocation(skill)
        loop = asyncio.get_running_loop()
        loop.create_task(session.run(f"[用户手动加载技能: {name}]\n{block}"))

    def _compact_skills_text(self) -> str:
        """Render the default Skill list as grouped, width-aware summaries."""
        name_width = 24
        description_width = max(28, min(72, self._transcript_width() - name_width - 4))
        lines = [f"可用技能 ({len(self._skills)})", ""]

        bootstrap = sorted(
            (skill for skill in self._skills if skill.bootstrap),
            key=lambda skill: skill.name,
        )
        if bootstrap:
            lines.append(f"自动引导 · {len(bootstrap)}")
            lines.extend(
                self._compact_skill_line(skill, name_width, description_width)
                for skill in bootstrap
            )
            lines.append("")

        groups: dict[str, list[Skill]] = {}
        for skill in self._skills:
            if skill.bootstrap:
                continue
            groups.setdefault(self._skill_group(skill), []).append(skill)
        for group_name, skills in self._ordered_skill_groups(groups):
            lines.append(f"{group_name} · {len(skills)}")
            lines.extend(
                self._compact_skill_line(skill, name_width, description_width)
                for skill in sorted(skills, key=lambda item: item.name)
            )
            lines.append("")

        lines.append("提示: /skills <name> 加载 · /skills info <name> 查看详情")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _skill_group(skill: Skill) -> str:
        if skill.package_id:
            return skill.package_id
        normalized = skill.path.replace("\\", "/")
        if "/resources/skills/" in normalized:
            return "内置技能"
        return "本地技能"

    @staticmethod
    def _ordered_skill_groups(groups: dict[str, list[Skill]]) -> list[tuple[str, list[Skill]]]:
        priority = {"内置技能": 1, "本地技能": 0}
        return sorted(
            groups.items(),
            key=lambda item: (priority.get(item[0], -1), item[0].lower()),
        )

    @staticmethod
    def _compact_skill_line(skill: Skill, name_width: int, description_width: int) -> str:
        description = " ".join(skill.description.split())
        if len(description) > description_width:
            description = description[: max(1, description_width - 3)].rstrip() + "..."
        return f"  {skill.name.ljust(name_width)} {description}"

    def _cmd_skill_info(self, args: tuple[str, ...]) -> None:
        """Show full metadata for one Skill without preloading its body."""
        if len(args) != 1:
            self.model.append_info("用法: /skills info <name>")
            return
        skill = self._skills_by_name.get(args[0])
        if skill is None:
            names = ", ".join(skill.name for skill in self._skills) or "(无)"
            self.model.append_info(f"未知技能: {args[0]}(可用: {names})")
            return
        lines = [
            "技能详情",
            f"名称: {skill.name}",
            f"描述: {skill.description}",
            f"来源: {skill.path}",
            f"类型: {'自动引导' if skill.bootstrap else '普通技能'}",
        ]
        if skill.package_id:
            version = skill.package_version or "unversioned"
            scope = skill.package_scope or "unknown"
            lines.append(f"Package: {skill.package_id}@{version} ({scope})")
            lines.append("扩展: 第三方扩展不会自动执行")
        lines.append(f"加载: /skills {skill.name}")
        self.model.append_info("\n".join(lines))

    def _cmd_skill_package(self, action: str, args: tuple[str, ...]) -> None:
        """执行 Package 生命周期命令；仅 reload 重建当前运行时。"""
        if self._package_action is None:
            self.model.append_info("当前环境不支持 Skill Package 操作")
            return
        try:
            message = self._package_action(action, args)
        except (KeyError, ValueError, OSError) as exc:
            message = f"Package 操作失败: {exc}"
        if action == "reload":
            self._refresh_skills()
        else:
            self.model.append_info("Package 状态已更新；执行 /skills reload 使当前会话生效")
        if message:
            self.model.append_info(message)

    def _cmd_mcp(self, cmd: Command) -> None:
        """/mcp:按 server 分组列出已加载 MCP 工具 + 装配诊断(对齐 Claude /mcp)。

        工具名 ``mcp__<server>__<tool>`` 解析回 server 分组;诊断(启动失败/
        裁剪)与工具列表并列展示——server 维度视图,加载结果可见可断言。
        """
        by_server: dict[str, list[str]] = {}
        for tool in self._manager.tools:
            name = getattr(tool, "name", "")
            if not name.startswith("mcp__"):
                continue
            parts = name.split("__", 2)
            server = parts[1] if len(parts) >= 2 else "?"
            tool_part = parts[2] if len(parts) >= 3 else name
            by_server.setdefault(server, []).append(tool_part)
        if not by_server and not self._mcp_diagnostics:
            self.model.append_info("MCP: (未配置 server)")
            return
        lines = ["MCP server:"]
        if by_server:
            for server in sorted(by_server):
                tools = ", ".join(sorted(by_server[server]))
                lines.append(f"  {server}: {tools}")
        else:
            lines.append("  (无已连接 server)")
        if self._mcp_diagnostics:
            lines.append("诊断:")
            lines.extend(f"  {message}" for message in self._mcp_diagnostics)
        self.model.append_info("\n".join(lines))

    def _cmd_tools(self, cmd: Command) -> None:
        names = [getattr(tool, "name", "") for tool in self._manager.tools]
        names = [n for n in names if n]
        text = "可用工具: " + ", ".join(names) if names else "可用工具: (无)"
        self.model.append_info(text)


    def _cmd_provider(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("provider")
            return
        self._apply_config(provider=cmd.args[0])

    def _cmd_login(self, cmd: Command) -> None:
        """/login:配置 provider 的 API key 并切换。

        无参 → provider 选择器(复用 picker 浮层);带参 → 校验后直通密钥输入态;
        登录态下输入框切换为掩码输入,提交保存、Esc 取消(见 _begin_login)。
        """
        if not cmd.args:
            self._open_inline_picker("login")
            return
        provider = cmd.args[0]
        if provider not in self._picker_candidates("login"):
            self.model.append_info(f"未知 provider: {provider}")
            return
        self._begin_login(provider)

    def _begin_login(self, provider: str) -> None:
        """进入密钥输入态:输入框切换掩码 + 提示;fake 无需密钥直通提示。"""
        if provider == "fake":
            # fake 无 API key 概念(离线脚本化客户端)。
            self.model.append_info("fake 无需密钥")
            self._schedule_render()
            return
        self._login_pending = provider
        self._suggestions = []
        self._backend.set_suggestions([])
        self._backend.set_input_mask(True)
        self._backend.set_input_placeholder(
            f"输入 {provider.upper()}_API_KEY,Enter 保存 / Esc 取消"
        )
        self.model.append_info(f"/login {provider}:请输入 API key(输入将隐藏)")
        self._schedule_render()

    def _end_login(self) -> None:
        """退出密钥输入态:恢复普通输入(掩码解除、提示还原)。"""
        self._login_pending = None
        self._backend.set_input_mask(False)

    def _cmd_model(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("model")
            return
        self._apply_config(model=cmd.args[0])

    def _cmd_effort(self, cmd: Command) -> None:
        if not cmd.args:
            self._open_inline_picker("effort")
            return
        self._apply_config(effort=cmd.args[0])

    def _apply_config(
        self, *, provider: str | None = None, model: str | None = None, effort: str | None = None
    ) -> bool:
        """配置热切换:经组合根注入的回调重建端口;未知值 ValueError 就地提示。

        返回是否切换成功(选择面板确认路径据此更新当前 provider 记录)。
        """
        if self._rebuild_ports is None:
            self.model.append_info("当前环境不支持热切换(未注入端口重建器)")
            return False
        try:
            new_model, new_effort = self._rebuild_ports(provider, model, effort)
        except ValueError as exc:
            self.model.append_info(str(exc))
            return False
        self.model.status.model = new_model
        self.model.status.effort = new_effort
        self._refresh_skills()
        self.model.append_info("已切换配置")
        return True



