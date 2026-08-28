"""技能来源发现和 Package Registry 投影。"""

from __future__ import annotations

from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from typing import Any

from .models import Skill, SkillDiagnostic, first_paragraph, parse_skill_frontmatter

SKILL_FILE = "SKILL.md"


def discover_skills_in(
    directory: Path,
    diagnostics: list[SkillDiagnostic],
    *,
    recursive: bool = False,
    package: Any = None,
) -> list[Skill]:
    """发现单个技能来源；直接目录一层，Package 目录递归。"""
    if not directory.is_dir():
        return []
    if recursive:
        candidates = sorted(directory.rglob(SKILL_FILE))
    else:
        candidates = [
            entry / SKILL_FILE
            for entry in sorted(directory.iterdir())
            if entry.is_dir() and not entry.name.startswith(".")
        ]
    found: list[Skill] = []
    for skill_file in candidates:
        if not skill_file.is_file():
            continue
        if recursive:
            try:
                relative = skill_file.resolve().relative_to(directory.resolve())
            except ValueError:
                diagnostics.append(
                    SkillDiagnostic("package_path_escape", f"Package Skill 路径越界: {skill_file}", str(skill_file))
                )
                continue
            if any(part.startswith(".") for part in relative.parts):
                continue
        skill, skill_diagnostics = parse_skill_file(
            skill_file,
            skill_file.parent.name,
            package=package,
            bootstrap=bool(package and getattr(package, "bootstrap", None) == skill_file.parent.name),
        )
        if skill is not None:
            found.append(skill)
        diagnostics.extend(skill_diagnostics)
    return found


def parse_skill_file(
    path: Path,
    directory_name: str,
    *,
    package: Any = None,
    bootstrap: bool = False,
) -> tuple[Skill | None, list[SkillDiagnostic]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, [SkillDiagnostic("read_failed", f"读取失败: {path}", str(path))]
    parsed = parse_skill_frontmatter(text)
    if parsed is None:
        return None, [SkillDiagnostic("parse_failed", f"frontmatter 解析失败: {path}", str(path))]
    frontmatter, body = parsed
    name = frontmatter.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else directory_name
    description = frontmatter.get("description")
    description = description.strip() if isinstance(description, str) and description.strip() else first_paragraph(body)
    if not description:
        return None, [
            SkillDiagnostic("invalid_metadata", f"缺少可用描述(无 description 且正文为空): {path}", str(path))
        ]
    return Skill(
        name=name,
        description=description,
        path=str(path),
        content=body,
        package_id=getattr(package, "package_id", None),
        package_version=getattr(package, "version", None),
        package_scope=getattr(package, "scope", None),
        bootstrap=bootstrap,
    ), []


def builtin_skills_dir() -> Path | None:
    resource = files("codeagent.resources").joinpath("skills")
    if not resource.is_dir():
        return None
    path = Path(str(resource))
    return path if path.is_dir() else None


def package_records(
    cwd: Path,
    config_dir: Path,
    diagnostics: list[SkillDiagnostic],
    scope: str,
) -> list[Any]:
    from codeagent.app.config import package_paths
    from .packages.registry import PackageRecord, PackageRegistry

    store_path, registry_path, _ = package_paths(cwd, scope=scope, config_dir=config_dir)
    raw, package_diags = PackageRegistry(registry_path).load()
    diagnostics.extend(
        SkillDiagnostic(f"package_{item.code}", item.message, item.path) for item in package_diags
    )
    records: list[PackageRecord] = []
    for value in raw:
        try:
            record = PackageRecord.from_dict(value)
            root = record.root.resolve()
            skills_dir = record.skills_dir.resolve()
            if not path_inside(store_path.resolve(), root):
                raise ValueError(f"Package 根目录越界: {root}")
            if not root.is_dir() or not skills_dir.is_dir():
                raise ValueError(f"Package Skill 根目录不存在: {skills_dir}")
            if not path_inside(root, skills_dir):
                raise ValueError(f"Package Skill 根目录越界: {skills_dir}")
            if record.bootstrap:
                bootstrap_path = (skills_dir / record.bootstrap / SKILL_FILE).resolve()
                if not path_inside(skills_dir, bootstrap_path) or not bootstrap_path.is_file():
                    diagnostics.append(
                        SkillDiagnostic(
                            "package_bootstrap_missing",
                            f"Package '{record.package_id}' Bootstrap 不存在: {record.bootstrap}",
                            str(bootstrap_path),
                        )
                    )
                    record = replace(record, bootstrap=None)
            if not record.bootstrap and (skills_dir / "using-superpowers" / SKILL_FILE).is_file():
                record = replace(record, bootstrap="using-superpowers")
                diagnostics.append(
                    SkillDiagnostic(
                        "package_bootstrap_inferred",
                        f"Package '{record.package_id}' 约定推断 Bootstrap: using-superpowers",
                        str(skills_dir / "using-superpowers" / SKILL_FILE),
                    )
                )
            records.append(record)
        except (ValueError, OSError) as exc:
            diagnostics.append(
                SkillDiagnostic("package_invalid", f"Package 记录无效: {exc}", str(value.get("root") or registry_path))
            )
    return sorted(records, key=lambda item: item.package_id)


def path_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False
