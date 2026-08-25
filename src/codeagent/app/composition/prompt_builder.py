"""AGENTS.md、Skill 和 system prompt 的组合根装配。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _workspace(cfg: Any = None) -> str:
    """解析装配工作目录，缺省使用进程启动目录。"""
    workspace = getattr(cfg, "cwd", None) if cfg is not None else None
    return str(Path(workspace or Path.cwd()).expanduser().resolve())


def _load_skills(cfg: Any = None) -> tuple[list[Any], list[Any]]:
    """加载 Skill 注册表与诊断，支持热切换重读。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.app.skills import load_skills

    return load_skills(_workspace(cfg), CONFIG_DIR)


def _build_system_prompt(cfg: Any = None, skills: list[Any] | None = None) -> str:
    """组装基础提示词、分层 AGENTS.md 和 Skill 描述。"""
    from codeagent.app import agents
    from codeagent.app.config import CONFIG_DIR

    base = agents.build_system_prompt(
        agents.read_base_prompt(), agents.load_agents_files(_workspace(cfg), CONFIG_DIR)
    )
    if skills is None:
        skills, _ = _load_skills(cfg)
    from codeagent.app.skill_runtime import build_bootstrap_prompt
    from codeagent.app.skills import build_skills_prompt

    base = build_bootstrap_prompt(base, skills)
    return build_skills_prompt(base, skills)


def agents_sources(cfg: Any = None) -> list[str]:
    """返回本次装配加载的上下文文件来源列表。"""
    from codeagent.app.agents import load_agents_files
    from codeagent.app.config import CONFIG_DIR

    return [path for path, _ in load_agents_files(_workspace(cfg), CONFIG_DIR)]


def skills_view(cfg: Any = None) -> tuple[list[Any], list[str]]:
    """返回 Skill 列表和面向 TUI 的一行诊断信息。"""
    skills, diagnostics = _load_skills(cfg)
    return skills, [f"{diagnostic.code}: {diagnostic.message}" for diagnostic in diagnostics]

