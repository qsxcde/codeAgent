"""skill 原子工具:按名称返回已加载技能的渲染正文块。

设计(design skills-system D3):
- **name 寻址替代"模型 read 技能文件"**:技能正文是系统在装配时加载的
  结果,不是工作区外文件——不走文件边界分类,安全分类器零改动;
- 注册表(技能名 → 渲染块)由组合根注入:``tools/`` 不 import app 层
  (test_decoupling 强制),渲染在组合根完成;未注入注册表时返回不可用提示;
- 未命中返回明确错误并列出可用技能名(模型可据此重试)。

分层约束:仅标准库,不 import core/session/ai/app。
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import OutputPolicy, ToolResourceLimits, govern_text

__all__ = ["SkillArgs", "SkillTool"]


class SkillArgs(BaseModel):
    name: str = Field(description="技能名称(来自 system 提示词的技能列表)")


class SkillTool(AtomicTool):
    name: ClassVar[str] = "skill"
    description: ClassVar[str] = "获取技能正文:按名称返回已加载技能的完整内容与使用说明。"
    Args: ClassVar[type[BaseModel]] = SkillArgs

    def __init__(
        self,
        cwd=None,
        ops=None,
        skills: dict[str, str] | None = None,
        resource_limits: ToolResourceLimits | None = None,
    ) -> None:
        """``skills`` 为技能名 → 渲染块 的注册表(组合根预渲染注入;None = 未注入)。"""
        super().__init__(cwd=cwd, ops=ops, resource_limits=resource_limits)
        self._skills: dict[str, str] = dict(skills or {})

    def _invoke(self, args: SkillArgs) -> str:
        if not self._skills:
            return "技能系统不可用:未注入技能注册表"
        block = self._skills.get(args.name)
        if block is None:
            names = ", ".join(sorted(self._skills))
            return f"技能不存在: {args.name}\n可用技能: {names or '(无)'}"
        return govern_text(block, OutputPolicy(direction="head"), source="tool")
