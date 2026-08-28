"""技能提示词格式化和多源技能注册。"""

from __future__ import annotations

from pathlib import Path

from .discovery import (
    SKILL_FILE,
    builtin_skills_dir,
    discover_skills_in,
    package_records,
    parse_skill_file,
    path_inside,
)
from .models import Skill, SkillDiagnostic, flatten, parse_skill_frontmatter

PROJECT_SKILLS_DIR = ".codeagent"

__all__ = [
    "Skill",
    "SkillDiagnostic",
    "build_skills_prompt",
    "format_skill_invocation",
    "load_skills",
    "parse_skill_frontmatter",
]

# 保留应用层旧的私有调用点，避免第三方适配器因拆分而失效。
_discover_skills_in = discover_skills_in
_parse_skill_file = parse_skill_file
_builtin_skills_dir = builtin_skills_dir
_package_records = package_records
_path_inside = path_inside


def format_skill_invocation(skill: Skill) -> str:
    """渲染技能正文块，供工具命中与用户手动加载共用。"""
    return (
        f'<skill name="{skill.name}" location="{skill.path}">\n'
        "引用相对路径以技能目录为基准。\n\n"
        f"{skill.content}\n"
        "</skill>"
    )


def build_skills_prompt(base: str, skills: list[Skill]) -> str:
    """在既有 system 提示词之后追加技能名称/描述/来源段。"""
    ordinary_skills = [skill for skill in skills if not skill.bootstrap]
    if not ordinary_skills:
        return base
    lines = [
        "<available_skills>",
        "技能按需使用:调用 skill 工具获取正文(参数为技能名);未列出的技能未加载。",
    ]
    lines.extend(
        f"- {skill.name}: {flatten(skill.description)} (来源: {skill.path})"
        for skill in sorted(ordinary_skills, key=lambda item: item.name)
    )
    lines.append("</available_skills>")
    return f"{base}\n\n" + "\n".join(lines)


def load_skills(
    cwd: str | Path,
    config_dir: str | Path,
    *,
    builtin_dir: str | Path | None = None,
) -> tuple[list[Skill], list[SkillDiagnostic]]:
    """按优先级发现技能、去重并报告同名遮蔽。"""
    diagnostics: list[SkillDiagnostic] = []
    resolved_cwd = Path(cwd).expanduser().resolve()
    resolved_config = Path(config_dir).expanduser().resolve()
    sources: list[tuple[str, Path, bool, object]] = [
        ("user", resolved_config / "skills", False, None),
    ]
    sources.extend(
        (f"user-package:{package.package_id}", package.skills_dir, True, package)
        for package in _package_records(resolved_cwd, resolved_config, diagnostics, "user")
    )
    sources.append(("project", resolved_cwd / PROJECT_SKILLS_DIR / "skills", False, None))
    sources.extend(
        (f"project-package:{package.package_id}", package.skills_dir, True, package)
        for package in _package_records(resolved_cwd, resolved_config, diagnostics, "project")
    )
    if builtin_dir is not None:
        sources.append(("builtin", Path(builtin_dir).expanduser().resolve(), False, None))
    else:
        builtin = _builtin_skills_dir()
        if builtin is not None:
            sources.append(("builtin", builtin, False, None))

    registry: dict[str, Skill] = {}
    seen_paths: set[str] = set()
    for source_name, source_dir, recursive, package in sources:
        for skill in _discover_skills_in(
            source_dir, diagnostics, recursive=recursive, package=package
        ):
            resolved_path = str(Path(skill.path).resolve())
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            shadowed = registry.get(skill.name)
            if shadowed is not None:
                diagnostics.append(
                    SkillDiagnostic(
                        "shadowed",
                        f"{source_name} 技能 '{skill.name}' 被更高优先级遮蔽: "
                        f"{shadowed.path} 已取代 {skill.path}",
                        skill.path,
                    )
                )
                continue
            registry[skill.name] = skill
    return sorted(registry.values(), key=lambda item: item.name), diagnostics
