"""app/skills.py:技能系统——SKILL.md 格式解析、多源加载与注册(纯函数)。

语义对齐 Claude Code Skills(2026-08-19 官方文档实查)与 Pi ``skills.ts``
(2026-08-15 源码实查):
- 一技能一目录,``SKILL.md`` = YAML frontmatter + Markdown 正文;
- 来源(优先级从高到低):个人级直接目录 > 个人级 Package > 项目级直接目录
  > 项目级 Package > 内建 ``resources/skills/``(Claude 语义:个人覆盖项目、
  任意级覆盖内建——与信任方向同向);
- ``name`` 缺省取目录名;``description`` 缺省取正文第一段(均不产生诊断);
- 解析失败 / 缺少可用 name 与 description → 诊断 + 跳过该技能,不中断加载
  (镜像 ``agents.py`` 读失败跳过风格);同名遮蔽产生诊断并标注遮蔽关系;
- ``format_skill_invocation`` 渲染块(对齐 Pi):技能工具与用户手动加载共用。

分层约束:本模块仅标准库 + yaml(第三方依赖,非跨层),
不 import core/session/ai/tools(test_decoupling 对 app/ 层强制)。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "Skill",
    "SkillDiagnostic",
    "build_skills_prompt",
    "format_skill_invocation",
    "load_skills",
    "parse_skill_frontmatter",
]

#: 项目级技能目录名(布局 <root>/skills/<name>/SKILL.md,Claude 式)。
PROJECT_SKILLS_DIR = ".codeagent"

#: 技能定义文件名。
SKILL_FILE = "SKILL.md"


@dataclass(frozen=True)
class Skill:
    """一个已加载的技能(名称、一行描述、来源路径与正文)。"""

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
    """技能加载诊断:稳定 code + 消息 + 关联路径(镜像 Pi SkillDiagnostic)。"""

    code: str  # parse_failed | invalid_metadata | shadowed
    message: str
    path: str = ""


def parse_skill_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    """解析 SKILL.md 的 YAML frontmatter,返回 (frontmatter, 正文)。

    - 不以 ``---`` 起始 → 无 frontmatter(空 dict,全文为正文);
    - ``---`` 起始但无闭合标记 → 按无 frontmatter 处理(对齐 Pi);
    - YAML 解析失败返回 None(调用方出 ``parse_failed`` 诊断)。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---"):
        return {}, normalized
    end = normalized.find("\n---", 3)
    if end == -1:
        return {}, normalized
    yaml_string = normalized[4:end]
    body = normalized[end + 4 :].strip()
    try:
        parsed = yaml.safe_load(yaml_string)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed, body


def _first_paragraph(text: str) -> str:
    """正文第一段(description 缺省值;空正文返回空串)。"""
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def _flatten(text: str) -> str:
    """多行文本压成一行(system prompt 技能行展示用)。"""
    return " ".join(part for part in text.splitlines() if part.strip())


def format_skill_invocation(skill: Skill) -> str:
    """渲染技能正文块(对齐 Pi ``formatSkillInvocation``)。

    技能工具命中与用户手动加载共用同一渲染函数,两条路径产出同一内容形态;
    标注"引用相对路径以技能目录为基准"(技能正文内相对引用的解析基准)。
    """
    return (
        f"<skill name=\"{skill.name}\" location=\"{skill.path}\">\n"
        f"引用相对路径以技能目录为基准。\n\n"
        f"{skill.content}\n"
        f"</skill>"
    )


def build_skills_prompt(base: str, skills: list[Skill]) -> str:
    """在既有 system 提示词之后追加技能段(渐进式披露:仅名称/描述/来源)。

    - 每个技能一行(名称 / 描述 / 来源路径),按名称排序(加载器已排);
    - 技能正文不进入提示词——模型按需经技能工具获取;
    - 无技能时不产生技能段。
    """
    ordinary_skills = [skill for skill in skills if not skill.bootstrap]
    if not ordinary_skills:
        return base
    lines = [
        "<available_skills>",
        "技能按需使用:调用 skill 工具获取正文(参数为技能名);未列出的技能未加载。",
    ]
    for skill in sorted(ordinary_skills, key=lambda s: s.name):  # 排序保证注入顺序确定
        lines.append(f"- {skill.name}: {_flatten(skill.description)} (来源: {skill.path})")
    lines.append("</available_skills>")
    return f"{base}\n\n" + "\n".join(lines)


def _discover_skills_in(
    directory: Path,
    diagnostics: list[SkillDiagnostic],
    *,
    recursive: bool = False,
    package: Any = None,
) -> list[Skill]:
    """单源发现:直接目录一层,Package 目录递归(解析失败诊断跳过)。

    直接目录保持旧版一层约定;Package 使用递归发现以兼容仓库中的分类目录。
    """
    found: list[Skill] = []
    if not directory.is_dir():
        return found
    if recursive:
        candidates = sorted(directory.rglob(SKILL_FILE))
    else:
        candidates = []
        for entry in sorted(directory.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                candidates.append(entry / SKILL_FILE)
    for skill_file in candidates:
        if not skill_file.is_file():
            continue
        if recursive:
            try:
                relative = skill_file.resolve().relative_to(directory.resolve())
            except ValueError:
                diagnostics.append(
                    SkillDiagnostic(
                        "package_path_escape",
                        f"Package Skill 路径越界: {skill_file}",
                        str(skill_file),
                    )
                )
                continue
            if any(part.startswith(".") for part in relative.parts):
                continue
        skill, diags = _parse_skill_file(
            skill_file,
            skill_file.parent.name,
            package=package,
            bootstrap=bool(package and getattr(package, "bootstrap", None) == skill_file.parent.name),
        )
        found.extend([skill] if skill is not None else [])
        diagnostics.extend(diags)
    return found


def _parse_skill_file(
    path: Path,
    directory_name: str,
    *,
    package: Any = None,
    bootstrap: bool = False,
) -> tuple[Skill | None, list[SkillDiagnostic]]:
    """解析单个 SKILL.md:frontmatter → name/description 缺省语义 + 校验。

    - name 缺省取目录名;description 缺省取正文第一段(均不产生诊断);
    - YAML 解析失败 → ``parse_failed`` 诊断,跳过;
    - 既无 frontmatter 描述也无可用正文 → ``invalid_metadata`` 诊断,跳过。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, [SkillDiagnostic("read_failed", f"读取失败: {path}", str(path))]
    parsed = parse_skill_frontmatter(text)
    if parsed is None:
        return None, [
            SkillDiagnostic("parse_failed", f"frontmatter 解析失败: {path}", str(path))
        ]
    frontmatter, body = parsed
    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        name = directory_name
    description = frontmatter.get("description")
    if isinstance(description, str) and description.strip():
        description = description.strip()
    else:
        description = _first_paragraph(body)
    if not description:
        return None, [
            SkillDiagnostic(
                "invalid_metadata", f"缺少可用描述(无 description 且正文为空): {path}", str(path)
            )
        ]
    return (
        Skill(
            name=name.strip(),
            description=description,
            path=str(path),
            content=body,
            package_id=getattr(package, "package_id", None),
            package_version=getattr(package, "version", None),
            package_scope=getattr(package, "scope", None),
            bootstrap=bootstrap,
        ),
        [],
    )


def _builtin_skills_dir() -> Path | None:
    """内建技能目录(包内 ``resources/skills/``;目录不存在返回 None)。

    ``uv_build`` 常规目录安装下 Traversable 即真实路径;压缩安装(如 zip)
    下无真实路径,技能正文仍可经内存渲染返回,仅来源标注不可直接访问。
    """
    resource = files("codeagent.resources").joinpath("skills")
    if not resource.is_dir():
        return None
    path = Path(str(resource))
    return path if path.is_dir() else None


def load_skills(
    cwd: str | Path,
    config_dir: str | Path,
    *,
    builtin_dir: str | Path | None = None,
) -> tuple[list[Skill], list[SkillDiagnostic]]:
    """多源发现 + 去重 + 同名遮蔽,返回 (按名称排序的技能表, 诊断列表)。

    - 来源顺序(优先级从高到低):个人级直接目录 → 个人级 Package → 项目级
      直接目录 → 项目级 Package → 内建(测试可注入 ``builtin_dir``);
    - 绝对路径去重(同文件只加载一次);同名遮蔽——高优先级源先入表,
      后到的同名技能产生 ``shadowed`` 诊断(标注谁遮蔽谁)并跳过;
    - 来源目录不存在静默跳过,不产生诊断。
    """
    diagnostics: list[SkillDiagnostic] = []
    resolved_cwd = Path(cwd).expanduser().resolve()
    resolved_config = Path(config_dir).expanduser().resolve()

    sources: list[tuple[str, Path, bool, Any]] = []
    sources.append(("user", resolved_config / "skills", False, None))
    # Package sources are inserted after the corresponding direct directory;
    # this preserves the existing personal > project > builtin behavior while
    # giving direct directories a deliberate override within each scope.
    for package in _package_records(resolved_cwd, resolved_config, diagnostics, "user"):
        sources.append((f"user-package:{package.package_id}", package.skills_dir, True, package))
    sources.append(("project", resolved_cwd / PROJECT_SKILLS_DIR / "skills", False, None))
    for package in _package_records(resolved_cwd, resolved_config, diagnostics, "project"):
        sources.append((f"project-package:{package.package_id}", package.skills_dir, True, package))
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
    return sorted(registry.values(), key=lambda s: s.name), diagnostics


def _package_records(
    cwd: Path,
    config_dir: Path,
    diagnostics: list[SkillDiagnostic],
    scope: str,
) -> list[Any]:
    """Load valid Package records for one scope without coupling callers."""
    from codeagent.app.config import package_paths
    from codeagent.app.skill_packages import PackageRecord, PackageRegistry

    store_path, registry_path, _ = package_paths(cwd, scope=scope, config_dir=config_dir)
    raw, package_diags = PackageRegistry(registry_path).load()
    diagnostics.extend(
        SkillDiagnostic(f"package_{item.code}", item.message, item.path)
        for item in package_diags
    )
    records: list[PackageRecord] = []
    for value in raw:
        try:
            record = PackageRecord.from_dict(value)
            root = record.root.resolve()
            skills_dir = record.skills_dir.resolve()
            if not _path_inside(store_path.resolve(), root):
                raise ValueError(f"Package 根目录越界: {root}")
            if not root.is_dir() or not skills_dir.is_dir():
                raise ValueError(f"Package Skill 根目录不存在: {skills_dir}")
            if not _path_inside(root, skills_dir):
                raise ValueError(f"Package Skill 根目录越界: {skills_dir}")
            if record.bootstrap:
                bootstrap_path = (skills_dir / record.bootstrap / SKILL_FILE).resolve()
                if not _path_inside(skills_dir, bootstrap_path) or not bootstrap_path.is_file():
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
                SkillDiagnostic(
                    "package_invalid",
                    f"Package 记录无效: {exc}",
                    str(value.get("root") or registry_path),
                )
            )
    return sorted(records, key=lambda item: item.package_id)


def _path_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False
