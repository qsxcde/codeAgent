"""CodeAgent-specific Skill Adapter and Bootstrap lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import Skill

BOOTSTRAP_TAG = "<codeagent_bootstrap>"
ADAPTER_VERSION = "codeagent-v1"


class CodeAgentAdapter:
    """Translate Superpowers' abstract actions to CodeAgent capabilities."""

    _TOOLS = (
        ("read files", "read"),
        ("write files", "write"),
        ("edit files", "edit"),
        ("run shell commands", "bash"),
        ("search file contents", "grep"),
        ("find files", "find"),
        ("list files", "ls"),
        ("invoke a skill", "skill"),
    )
    _CAPABILITIES = {
        "read": True,
        "write": True,
        "edit": True,
        "bash": True,
        "grep": True,
        "find": True,
        "ls": True,
        "skill": True,
        "subagents": False,
        "todo": False,
        "web": False,
    }

    @property
    def version(self) -> str:
        return ADAPTER_VERSION

    def tool_mapping(self) -> str:
        lines = ["CodeAgent 工具映射:"]
        lines.extend(f"- {action} -> `{tool}`" for action, tool in self._TOOLS)
        lines.extend(
            [
                "- subagent dispatch -> 当前不可用,按 Skill 中的 inline/fallback 流程执行",
                "- todo/task tracking -> 当前不可用,使用计划或 TODO 文件降级",
                "- web fetch/search -> 当前不可用,不得调用不存在的工具",
            ]
        )
        return "\n".join(lines)

    def capabilities(self) -> dict[str, bool]:
        return dict(self._CAPABILITIES)

    def select_bootstrap(self, skills: Iterable[Skill]) -> Skill | None:
        return next((skill for skill in skills if skill.bootstrap), None)

    def render_bootstrap(self, skill: Skill) -> str:
        return (
            f"{BOOTSTRAP_TAG}\n"
            f"适配器版本: {self.version}\n"
            f"Bootstrap Skill: {skill.name}\n"
            "以下 Bootstrap 是当前会话的强制工作流入口。\n\n"
            f"{skill.content}\n\n"
            f"{self.tool_mapping()}\n"
            "</codeagent_bootstrap>"
        )


def build_bootstrap_prompt(base: str, skills: Iterable[Skill]) -> str:
    """Append the one selected bootstrap without preloading ordinary skills."""

    adapter = CodeAgentAdapter()
    bootstrap = adapter.select_bootstrap(skills)
    if bootstrap is None:
        return base
    return f"{base}\n\n{adapter.render_bootstrap(bootstrap)}"


@dataclass
class SkillRuntimeState:
    """Session/context dedup state exposed to status and lifecycle callers."""

    adapter_version: str = ADAPTER_VERSION
    bootstrap_name: str | None = None
    _claimed_contexts: set[str] = field(default_factory=set)

    def claim(self, context_id: str) -> bool:
        if context_id in self._claimed_contexts:
            return False
        self._claimed_contexts.add(context_id)
        return True

    def reset(self, context_id: str | None = None) -> None:
        if context_id is None:
            self._claimed_contexts.clear()
        else:
            self._claimed_contexts.discard(context_id)

    def status(self) -> dict[str, object]:
        return {
            "adapter": self.adapter_version,
            "bootstrap": self.bootstrap_name,
            "contexts": len(self._claimed_contexts),
        }
