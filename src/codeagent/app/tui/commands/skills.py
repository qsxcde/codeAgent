"""TUI 的技能列表、手动加载与 Package 命令协作者。"""

from __future__ import annotations

import asyncio
import inspect

from codeagent.app.errors.reporting import report_unexpected_error
from codeagent.app.skills.models import Skill
from codeagent.app.skills.prompt import format_skill_invocation
from .parser import Command


class TuiSkillCommandCoordinator:
    def _cmd_skills(self, cmd: Command) -> None:
        if not cmd.args:
            self.model.append_info(self._compact_skills_text() if self._skills else "技能: (无)")
            return
        action = cmd.args[0]
        if action == "info":
            self._cmd_skill_info(cmd.args[1:])
            return
        if action in {"install", "list", "update", "remove", "reload"}:
            self._cmd_skill_package(action, cmd.args[1:])
            return
        skill = self._skills_by_name.get(action)
        if skill is None:
            names = ", ".join(skill.name for skill in self._skills) or "(无)"
            self.model.append_info(f"未知技能: {action}(可用: {names})")
            return
        session = self._manager.current
        if session is None:
            self.model.append_info("(无当前会话)")
            return
        self._track_task(
            asyncio.get_running_loop().create_task(
                session.run(f"[用户手动加载技能: {action}]\n{format_skill_invocation(skill)}")
            )
        )

    def _compact_skills_text(self) -> str:
        name_width = 24
        description_width = max(28, min(72, self._transcript_width() - name_width - 4))
        lines = [f"可用技能 ({len(self._skills)})", ""]
        groups: dict[str, list[Skill]] = {}
        for skill in self._skills:
            groups.setdefault("自动引导" if skill.bootstrap else self._skill_group(skill), []).append(skill)
        for group, skills in self._ordered_skill_groups(groups):
            lines.append(f"{group} · {len(skills)}")
            lines.extend(self._compact_skill_line(skill, name_width, description_width) for skill in sorted(skills, key=lambda item: item.name))
            lines.append("")
        lines.append("提示: /skills <name> 加载 · /skills info <name> 查看详情")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _skill_group(skill: Skill) -> str:
        if skill.package_id:
            return skill.package_id
        return "内置技能" if "/resources/skills/" in skill.path.replace("\\", "/") else "本地技能"

    @staticmethod
    def _ordered_skill_groups(groups: dict[str, list[Skill]]) -> list[tuple[str, list[Skill]]]:
        priority = {"自动引导": 2, "内置技能": 1, "本地技能": 0}
        return sorted(groups.items(), key=lambda item: (priority.get(item[0], -1), item[0].lower()), reverse=True)

    @staticmethod
    def _compact_skill_line(skill: Skill, name_width: int, description_width: int) -> str:
        description = " ".join(skill.description.split())
        if len(description) > description_width:
            description = description[: max(1, description_width - 3)].rstrip() + "..."
        return f"  {skill.name.ljust(name_width)} {description}"

    def _cmd_skill_info(self, args: tuple[str, ...]) -> None:
        if len(args) != 1:
            self.model.append_info("用法: /skills info <name>")
            return
        skill = self._skills_by_name.get(args[0])
        if skill is None:
            self.model.append_info(f"未知技能: {args[0]}")
            return
        lines = ["技能详情", f"名称: {skill.name}", f"描述: {skill.description}", f"来源: {skill.path}", f"类型: {'自动引导' if skill.bootstrap else '普通技能'}"]
        if skill.package_id:
            lines.extend([f"Package: {skill.package_id}@{skill.package_version or 'unversioned'} ({skill.package_scope or 'unknown'})", "扩展: 第三方扩展不会自动执行"])
        self.model.append_info("\n".join([*lines, f"加载: /skills {skill.name}"]))

    def _cmd_skill_package(self, action: str, args: tuple[str, ...]) -> None:
        if self._package_action is None:
            self.model.append_info("当前环境不支持 Skill Package 操作")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._apply_package_action(action, args)
            return
        self.model.append_info("正在执行 Skill Package 操作...")
        self._package_task = self._track_task(loop.create_task(self._run_package_action(action, args)))

    async def _run_package_action(self, action: str, args: tuple[str, ...]) -> None:
        try:
            result = await asyncio.to_thread(self._package_action, action, args)
            result = await result if inspect.isawaitable(result) else result
        except Exception as exc:
            self.model.append_info(report_unexpected_error("Package 操作", exc))
        else:
            self._show_package_result(action, str(result or ""))
        self._schedule_render()

    def _apply_package_action(self, action: str, args: tuple[str, ...]) -> None:
        try:
            message = self._package_action(action, args)
        except Exception as exc:
            self.model.append_info(report_unexpected_error("Package 操作", exc))
            return
        self._show_package_result(action, str(message or ""))

    def _show_package_result(self, action: str, message: str) -> None:
        if action == "reload":
            self._refresh_skills()
        else:
            self.model.append_info("Package 状态已更新；执行 /skills reload 使当前会话生效")
        if message:
            self.model.append_info(message)
