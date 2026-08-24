"""tests/test_skills.py:技能系统测试(加载器 + skill 工具,全部离线)。

对应 spec skills「SKILL.md 格式与发现」「加载与同名遮蔽」「渐进式披露注入」
「技能工具」「加载结果可见」。镜像 test_agents.py:临时目录树,零真实依赖;
内建来源经 ``builtin_dir`` 注入测试缝,不依赖包内示例技能。
"""

from pathlib import Path

from codeagent.app.skills import (
    build_skills_prompt,
    format_skill_invocation,
    load_skills,
    parse_skill_frontmatter,
)
from codeagent.app.skill_packages import PackageManager
from codeagent.tools.atomic import SkillTool

_BLOCK_HEAD = "<skill name="


def _write_skill(skill_dir: Path, frontmatter: str = "", body: str = "正文"):
    """写一个技能目录(一技能一目录 SKILL.md)。"""
    skill_dir.mkdir(parents=True, exist_ok=True)
    text = f"---\n{frontmatter}---\n{body}" if frontmatter else body
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")


def _tree(tmp_path):
    """三源目录树:个人级 config_dir + 项目级 cwd + 内建(builtin_dir 注入)。"""
    config_dir = tmp_path / ".config"
    cwd = tmp_path / "proj"
    builtin = tmp_path / "builtin"
    return config_dir, cwd, builtin


# ── 格式与发现 ─────────────────────────────────────────


def test_parse_frontmatter_basic():
    """frontmatter 解析:name/description + 正文分离。"""
    parsed = parse_skill_frontmatter("---\nname: fmt\ndescription: 格式化。\n---\n正文")
    assert parsed is not None
    frontmatter, body = parsed
    assert frontmatter == {"name": "fmt", "description": "格式化。"}
    assert body == "正文"


def test_parse_frontmatter_without_delimiters():
    """无 --- 起始 → 无 frontmatter(全文为正文)。"""
    parsed = parse_skill_frontmatter("纯正文\n第二行")
    assert parsed == ({}, "纯正文\n第二行")


def test_parse_frontmatter_unclosed():
    """--- 起始但无闭合标记 → 按无 frontmatter 处理(对齐 Pi)。"""
    parsed = parse_skill_frontmatter("---\nname: x\n没有闭合")
    assert parsed == ({}, "---\nname: x\n没有闭合")


def test_parse_frontmatter_yaml_error():
    """YAML 语法错误 → None(调用方出 parse_failed 诊断)。"""
    assert parse_skill_frontmatter("---\nname: [unclosed\n---\nxx") is None


def test_parse_frontmatter_block_scalar():
    """生态文件常见块标量 description(|)能正确解析(复制即用)。"""
    parsed = parse_skill_frontmatter(
        '---\ndescription: |\n  第一行说明。\n  第二行说明。\nname: fmt\n---\n正文'
    )
    assert parsed is not None
    frontmatter, body = parsed
    assert frontmatter["description"].startswith("第一行说明。")
    assert body == "正文"


def test_discover_name_defaults_to_dirname(tmp_path):
    """name 缺省取目录名;description 缺省取正文第一段(不产生诊断)。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    _write_skill(tmp_path / "proj" / ".codeagent" / "skills" / "my-skill", body="第一段说明。\n其余正文")
    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert not diagnostics
    assert len(skills) == 1
    assert skills[0].name == "my-skill"
    assert skills[0].description == "第一段说明。"


def test_parse_failure_skipped_with_diagnostic(tmp_path):
    """frontmatter 解析失败 → 诊断 + 跳过,其它技能照常。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    _write_skill(tmp_path / "proj" / ".codeagent" / "skills" / "broken",
                 frontmatter="name: [unclosed\n")
    _write_skill(tmp_path / "proj" / ".codeagent" / "skills" / "good",
                 frontmatter="description: 好的技能。\n")
    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert [s.name for s in skills] == ["good"]
    assert any(d.code == "parse_failed" for d in diagnostics)


def test_missing_name_and_description_skipped(tmp_path):
    """既无 name/description 也无可用正文 → 诊断 + 跳过。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    _write_skill(tmp_path / "proj" / ".codeagent" / "skills" / "empty", body="")
    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert skills == []
    assert any(d.code == "invalid_metadata" for d in diagnostics)


def test_missing_source_dir_silently_skipped(tmp_path):
    """来源目录不存在 → 静默跳过,不产生诊断。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert skills == [] and diagnostics == []


def test_three_sources_all_discovered(tmp_path):
    """内建 + 个人级 + 项目级全部进入加载。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    _write_skill(builtin / "b-in", frontmatter="description: 内建。\n")
    _write_skill(config_dir / "skills" / "u-fmt", frontmatter="description: 个人。\n")
    _write_skill(cwd / ".codeagent" / "skills" / "p-fmt", frontmatter="description: 项目。\n")
    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert not diagnostics
    assert {s.name for s in skills} == {"b-in", "u-fmt", "p-fmt"}


def test_registry_sorted_by_name(tmp_path):
    """注册表按名称字典序输出。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    _write_skill(config_dir / "skills" / "zeta", frontmatter="description: z。\n")
    _write_skill(config_dir / "skills" / "alpha", frontmatter="description: a。\n")
    _write_skill(config_dir / "skills" / "mid", frontmatter="description: m。\n")
    skills, _ = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert [s.name for s in skills] == ["alpha", "mid", "zeta"]


# ── 遮蔽(个人 > 项目 > 内建)───────────────────────────


def test_user_shadows_project(tmp_path):
    """同名技能:个人级覆盖项目级,被遮蔽者产生诊断(标注遮蔽关系)。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    user_skill = config_dir / "skills" / "fmt"
    project_skill = cwd / ".codeagent" / "skills" / "fmt"
    _write_skill(user_skill, frontmatter="description: 用户版。\n", body="用户正文")
    _write_skill(project_skill, frontmatter="description: 项目版。\n")
    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert [s.name for s in skills] == ["fmt"]
    assert skills[0].description == "用户版。"
    shadowed = [d for d in diagnostics if d.code == "shadowed"]
    assert len(shadowed) == 1
    assert str(project_skill.resolve()) in shadowed[0].message
    assert str(user_skill.resolve()) in shadowed[0].message


def test_any_level_shadows_builtin(tmp_path):
    """项目级技能覆盖同名内建技能。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    _write_skill(builtin / "fmt", frontmatter="description: 内建版。\n")
    _write_skill(cwd / ".codeagent" / "skills" / "fmt", frontmatter="description: 项目版。\n")
    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert skills[0].description == "项目版。"
    assert any(d.code == "shadowed" for d in diagnostics)


def test_same_path_not_loaded_twice(tmp_path):
    """同一绝对路径只加载一次(如 cwd 与个人级指向同一文件)。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    skill_dir = tmp_path / "shared" / "fmt"
    _write_skill(skill_dir, frontmatter="description: 同一文件。\n")
    # 个人级与项目级目录都不存在时,把同一目录同时作为两个来源注入不可行
    # (load_skills 固定来源);改为:两来源中同一文件出现两次仅加载一次——
    # 通过把个人级目录符号链接到项目级目录验证(Unix);Windows 跳过。
    import os

    if os.name == "nt":
        return
    (config_dir / "skills").mkdir(parents=True)
    (cwd / ".codeagent" / "skills").mkdir(parents=True)
    os.symlink(str(skill_dir), str(config_dir / "skills" / "fmt"))
    os.symlink(str(skill_dir), str(cwd / ".codeagent" / "skills" / "fmt"))
    skills, _ = load_skills(cwd, config_dir, builtin_dir=builtin)
    assert len(skills) == 1


def test_package_skills_are_discovered_recursively_with_metadata(tmp_path):
    """已安装 Package 的嵌套 skills 目录被递归发现并保留来源元数据。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    package_root = tmp_path / "package-source"
    nested = package_root / "skills" / "category" / "nested-skill"
    _write_skill(nested, frontmatter="description: 包内技能。\n")
    (package_root / "codeagent-package.json").write_text(
        '{"id":"demo","name":"Demo","version":"1.2.3","skills":"skills"}',
        encoding="utf-8",
    )
    PackageManager(config_dir, cwd).install(package_root, scope="user")

    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)

    assert not [d for d in diagnostics if d.code.startswith("package_")]
    loaded = next(item for item in skills if item.name == "nested-skill")
    assert loaded.package_id == "demo"
    assert loaded.package_version == "1.2.3"
    assert loaded.package_scope == "user"


def test_skill_source_priority_is_direct_then_package_then_project(tmp_path):
    """个人直接目录 > 个人 Package > 项目直接目录 > 项目 Package。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    _write_skill(config_dir / "skills" / "shared", frontmatter="description: 用户直接。\n")
    _write_skill(cwd / ".codeagent" / "skills" / "project-only", frontmatter="description: 项目直接。\n")

    package_root = tmp_path / "package-source"
    _write_skill(package_root / "skills" / "shared", frontmatter="description: 用户包。\n")
    _write_skill(package_root / "skills" / "package-only", frontmatter="description: 用户包独有。\n")
    (package_root / "codeagent-package.json").write_text(
        '{"id":"demo","version":"1.0.0","skills":"skills"}', encoding="utf-8"
    )
    PackageManager(config_dir, cwd).install(package_root, scope="user")

    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)

    by_name = {item.name: item for item in skills}
    assert by_name["shared"].description == "用户直接。"
    assert by_name["package-only"].package_id == "demo"
    assert any(d.code == "shadowed" for d in diagnostics)


def test_package_using_superpowers_is_inferred_as_bootstrap(tmp_path):
    """无 CodeAgent 清单时按约定识别 using-superpowers Bootstrap。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    package_root = tmp_path / "package-source"
    _write_skill(
        package_root / "skills" / "using-superpowers",
        frontmatter="description: 启动引导。\n",
        body="检查相关技能。",
    )
    (package_root / "codeagent-package.json").write_text(
        '{"id":"superpowers","version":"6.3.0","skills":"skills"}', encoding="utf-8"
    )
    PackageManager(config_dir, cwd).install(package_root, scope="user")

    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)

    bootstrap = next(item for item in skills if item.name == "using-superpowers")
    assert bootstrap.bootstrap is True
    assert any(d.code == "package_bootstrap_inferred" for d in diagnostics)


def test_superpowers_package_loads_skills_without_executing_harness_extensions(tmp_path):
    """Superpowers 兼容验收:读取 Markdown，忽略 .pi/.opencode 等扩展入口。"""
    config_dir, cwd, builtin = _tree(tmp_path)
    package_root = tmp_path / "superpowers"
    _write_skill(
        package_root / "skills" / "using-superpowers",
        frontmatter="description: 启动引导。\n",
        body="开始任务前检查相关 Skill。",
    )
    _write_skill(
        package_root / "skills" / "brainstorming",
        frontmatter="description: 需求澄清。\n",
        body="先澄清目标。",
    )
    (package_root / ".pi" / "extensions").mkdir(parents=True)
    (package_root / ".pi" / "extensions" / "danger.py").write_text(
        "raise RuntimeError('must not execute')", encoding="utf-8"
    )
    (package_root / ".opencode" / "plugin.ts").parent.mkdir(parents=True)
    (package_root / ".opencode" / "plugin.ts").write_text("throw new Error()", encoding="utf-8")
    PackageManager(config_dir, cwd).install(package_root, scope="user")

    skills, diagnostics = load_skills(cwd, config_dir, builtin_dir=builtin)

    assert {item.name for item in skills} == {"brainstorming", "using-superpowers"}
    assert next(item for item in skills if item.name == "using-superpowers").bootstrap is True
    assert not any("danger.py" in diagnostic.message for diagnostic in diagnostics)


# ── 渐进式披露注入 ─────────────────────────────────────


def _sample_skill():
    from codeagent.app.skills import Skill

    return Skill(
        name="fmt",
        description="格式化代码。",
        path="/skills/fmt/SKILL.md",
        content="正文内容",
    )


def test_build_skills_prompt_appends_section():
    """技能段位于基础提示词之后,每技能一行(名称/描述/来源),按名称排序。"""
    from codeagent.app.skills import Skill

    skills = [
        Skill("zeta", "z 描述。", "/z/SKILL.md", "BODY-Z"),
        Skill("alpha", "a 描述。", "/a/SKILL.md", "BODY-A"),
    ]
    prompt = build_skills_prompt("基础提示词", skills)
    assert prompt.startswith("基础提示词")
    assert "<available_skills>" in prompt
    assert prompt.index("alpha") < prompt.index("zeta")
    assert "- alpha: a 描述。 (来源: /a/SKILL.md)" in prompt
    assert "BODY-Z" not in prompt and "BODY-A" not in prompt  # 正文不预载
    assert prompt.endswith("</available_skills>")


def test_build_skills_prompt_empty_no_section():
    """无技能 → 不产生技能段。"""
    assert build_skills_prompt("基础", []) == "基础"


def test_format_skill_invocation_block():
    """渲染块:技能名 + 来源标注 + 相对路径基准说明 + 正文。"""
    block = format_skill_invocation(_sample_skill())
    assert '<skill name="fmt" location="/skills/fmt/SKILL.md">' in block
    assert "引用相对路径以技能目录为基准" in block
    assert "正文内容" in block
    assert block.endswith("</skill>")


# ── skill 工具 ─────────────────────────────────────────


def test_skill_tool_hit_returns_rendered_block():
    """命中返回渲染块(与加载器渲染同源)。"""
    tool = SkillTool(skills={"fmt": format_skill_invocation(_sample_skill())})
    out = tool.invoke(SkillTool.Args(name="fmt"))
    assert _BLOCK_HEAD in out and "正文内容" in out


def test_skill_tool_miss_lists_available():
    """未命中报错并列出可用技能名。"""
    tool = SkillTool(skills={"fmt": "block"})
    out = tool.invoke(SkillTool.Args(name="nope"))
    assert "技能不存在: nope" in out
    assert "fmt" in out


def test_skill_tool_without_registry():
    """未注入注册表 → 返回不可用提示。"""
    tool = SkillTool()
    out = tool.invoke(SkillTool.Args(name="fmt"))
    assert "未注入技能注册表" in out
