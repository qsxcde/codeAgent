"""技能领域模型和 SKILL.md frontmatter 解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: str
    content: str
    package_id: str | None = None
    package_version: str | None = None
    package_scope: str | None = None
    bootstrap: bool = False


@dataclass(frozen=True)
class SkillDiagnostic:
    code: str
    message: str
    path: str = ""


def parse_skill_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    """解析 SKILL.md 的 YAML frontmatter。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---"):
        return {}, normalized
    end = normalized.find("\n---", 3)
    if end == -1:
        return {}, normalized
    try:
        parsed = yaml.safe_load(normalized[4:end])
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed, normalized[end + 4 :].strip()


def first_paragraph(text: str) -> str:
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def flatten(text: str) -> str:
    return " ".join(part for part in text.splitlines() if part.strip())
