"""会话模式、输入解析和只读权限边界。

模式是应用层策略，不进入通用 ReAct 循环。应用组合根把这里生成的策略
注入一次运行，因而 ``core`` 不需要知道 ask/plan/code 的产品语义。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "TaskMode",
    "ModeInput",
    "ModeParseError",
    "parse_mode_input",
    "mode_policy",
    "is_mutating_command",
]


class TaskMode(StrEnum):
    ASK = "ask"
    PLAN = "plan"
    CODE = "code"
    AUTO = "auto"


class ModeParseError(ValueError):
    """模式命令格式错误。"""


@dataclass(frozen=True)
class ModeInput:
    """解析后的输入；``sticky`` 表示是否改变后续粘性模式。"""

    mode: TaskMode
    text: str
    sticky: bool = False
    next_sticky: TaskMode = TaskMode.AUTO


@dataclass(frozen=True)
class _ModeDecision:
    """与 core PolicyDecision 同形的应用层值对象，避免反向依赖 core。"""

    action: str
    reason: str = ""
    warning: bool = False


def parse_mode_input(text: str, *, sticky: TaskMode = TaskMode.AUTO) -> ModeInput:
    """解析单次模式前缀和 ``/mode`` 粘性命令。

    普通输入保留原文；``//`` 仍作为字面量转义，不会被当成模式命令。
    """
    if not isinstance(sticky, TaskMode):
        sticky = TaskMode(str(sticky))
    raw = text.strip()
    if raw.startswith("//"):
        return ModeInput(sticky, raw[1:], False, sticky)
    if not raw.startswith("/"):
        return ModeInput(sticky, text, False, sticky)

    command, _, argument = raw[1:].partition(" ")
    command = command.strip().lower()
    argument = argument.strip()
    if command in {TaskMode.ASK.value, TaskMode.PLAN.value, TaskMode.CODE.value}:
        return ModeInput(TaskMode(command), argument, False, sticky)
    if command == "mode":
        if not argument or len(argument.split()) != 1:
            raise ModeParseError("用法: /mode ask|plan|code|auto")
        try:
            selected = TaskMode(argument.lower())
        except ValueError as exc:
            raise ModeParseError(
                f"未知模式: {argument}；可选 ask、plan、code、auto"
            ) from exc
        return ModeInput(selected, "", True, selected)
    return ModeInput(sticky, text, False, sticky)


_MUTATING_TOOL_NAMES = frozenset({"write", "edit", "delete", "remove", "mv", "cp", "mkdir"})
_MUTATING_COMMAND_RE = re.compile(
    r"(?:^|[;&|])\s*(?:rm|rmdir|del|erase|mv|cp|copy|move|touch|mkdir|"
    r"install|npm\s+(?:install|uninstall)|pip\s+install|git\s+(?:checkout|reset|clean|commit|push)|"
    r"sed\s+-i|perl\s+-i)\b|(?:>|>>|\btee\b)",
    re.IGNORECASE,
)


def is_mutating_command(command: str) -> bool:
    """保守识别 ask/plan 中不能执行的 shell 命令。"""
    return bool(_MUTATING_COMMAND_RE.search(command.strip()))


class _ModePolicy:
    def __init__(self, base: Any, mode: TaskMode) -> None:
        self._base = base
        self._mode = mode

    def decide(self, tool_name: str, args: dict[str, Any]) -> _ModeDecision:
        if self._mode in {TaskMode.ASK, TaskMode.PLAN}:
            if tool_name.lower() in _MUTATING_TOOL_NAMES:
                return _ModeDecision(
                    "deny",
                    f"{self._mode.value} 模式为只读，无法执行 {tool_name}；请切换到 /code",
                )
            if tool_name.lower() == "bash" and is_mutating_command(
                str(args.get("command") or "")
            ):
                return _ModeDecision(
                    "deny",
                    f"{self._mode.value} 模式为只读，无法执行变更型命令；请切换到 /code",
                )
        if self._base is None:
            return _ModeDecision("allow")
        decision = self._base.decide(tool_name, args)
        if decision is None:
            return _ModeDecision("allow")
        return decision


def mode_policy(base: Any, mode: TaskMode) -> Any:
    """为一次任务生成模式策略；code/auto 直接复用基础策略。"""
    if not isinstance(mode, TaskMode):
        mode = TaskMode(str(mode))
    if mode in {TaskMode.ASK, TaskMode.PLAN}:
        return _ModePolicy(base, mode)
    return base
