"""tests/test_agents.py:分层上下文文件加载器与 system prompt 合并(纯函数)。

对应 spec core「系统提示词注入」:分层合并与优先级、候选文件名与去重、
来源标注、加载结果可见。全部用临时目录树,零真实文件依赖。
"""

from pathlib import Path

import pytest

import codeagent.app.context.agents as agents_module
from codeagent.app.context.agents import (
    AGENTS_CANDIDATES,
    build_system_prompt,
    load_agents_files,
    read_base_prompt,
)


@pytest.fixture(autouse=True)
def _isolate_ancestor_context(monkeypatch, tmp_path):
    """单元测试只读取临时目录树,不受运行机器上的上级指令文件影响。"""
    real_first_candidate = agents_module._first_candidate
    test_root = tmp_path.resolve()

    def isolated_first_candidate(directory: Path) -> Path | None:
        try:
            directory.resolve().relative_to(test_root)
        except ValueError:
            return None
        return real_first_candidate(directory)

    monkeypatch.setattr(agents_module, "_first_candidate", isolated_first_candidate)


def _write(directory, name: str, content: str = "内容"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(content, encoding="utf-8")


def _tree(tmp_path):
    """构造目录树:全局配置目录 + 项目根 + 两级子目录。"""
    config_dir = tmp_path / ".config"
    root = tmp_path / "proj"
    sub1 = root / "src" / "pkg"
    _write(config_dir, "AGENTS.md", "全局指令")
    _write(root, "AGENTS.md", "项目指令")
    _write(sub1, "AGENTS.md", "子目录指令")
    return config_dir, root, sub1


def test_loads_global_then_ancestors_nearest_last(tmp_path):
    """顺序:全局最前,越近 cwd 越靠后(优先级越高)。"""
    config_dir, root, sub1 = _tree(tmp_path)
    result = load_agents_files(sub1, config_dir)
    assert [Path(p).name for p, _ in result] == ["AGENTS.md", "AGENTS.md", "AGENTS.md"]
    assert result[0][0].startswith(str(config_dir))  # 全局
    assert "全局指令" in result[0][1]
    assert result[-1][0].startswith(str(sub1))  # 最近目录最后
    assert result[-1][1] == "子目录指令"


def test_candidate_priority_order(tmp_path):
    """候选表优先级:AGENTS.override.md > AGENTS.md > CLAUDE.md。"""
    config_dir = tmp_path / ".config"
    root = tmp_path / "proj"
    _write(config_dir, "AGENTS.override.md", "override")
    _write(config_dir, "AGENTS.md", "agents")
    _write(root, "CLAUDE.md", "claude")
    result = load_agents_files(root, config_dir)
    assert len(result) == 2
    assert "override" in result[0][1]  # 全局取 override
    assert "claude" in result[1][1]  # 项目取 CLAUDE(无 AGENTS)


def test_deduplicates_same_file(tmp_path):
    """同一文件不重复注入(如 cwd 与祖先解析到同一绝对路径)。"""
    config_dir = tmp_path / ".config"
    root = tmp_path / "proj"
    _write(config_dir, "AGENTS.md", "全局")
    _write(root, "AGENTS.md", "项目")
    # cwd 指向 root 的子目录但该目录无 AGENTS → 只应出现全局 + 项目各一次
    nested = root / "nested"
    nested.mkdir(parents=True)
    result = load_agents_files(nested, config_dir)
    paths = [p for p, _ in result]
    assert len(paths) == len(set(paths)) == 2


def test_unreadable_file_skipped(tmp_path, monkeypatch):
    """读失败跳过,不中断加载(其它文件照常)。

    读失败经 mock 注入 PermissionError:chmod(0) 在 Windows 上无效果,
    按平台跳过后断言又无条件执行会制造非确定失败(审计 M-1)。
    """
    config_dir = tmp_path / ".config"
    root = tmp_path / "proj"
    _write(config_dir, "AGENTS.md", "全局")
    _write(root, "AGENTS.md", "项目")
    locked = root / "sub"
    _write(locked, "AGENTS.md", "子目录")
    locked_file = locked / "AGENTS.md"
    real_read_text = Path.read_text

    def flaky_read_text(self: Path, *args, **kwargs):
        """只对目标文件抛 PermissionError,其余正常读(仅作用于本测试)。"""
        if self == locked_file:
            raise PermissionError(f"模拟不可读: {self}")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    result = load_agents_files(locked, config_dir)
    assert len(result) == 2  # 全局 + 项目(子目录读失败被跳过)
    assert str(locked_file.resolve()) not in [p for p, _ in result]  # 失败文件未混入


def test_build_system_prompt_annotates_sources():
    """合并格式:来源 path 标注 + 内容包裹(Pi 式 project_instructions)。"""
    base = "基础提示词"
    agents = [("/a/AGENTS.md", "全局"), ("/a/sub/AGENTS.md", "子目录")]
    prompt = build_system_prompt(base, agents)
    assert prompt.startswith(base)
    assert "<project_context>" in prompt
    assert '<project_instructions path="/a/AGENTS.md">' in prompt
    assert '<project_instructions path="/a/sub/AGENTS.md">' in prompt
    assert "全局" in prompt and "子目录" in prompt
    assert "</project_context>" in prompt


def test_build_system_prompt_without_agents():
    """无上下文文件 → 仅基础提示词,不产生空 project_context 段。"""
    assert build_system_prompt("基础", []) == "基础"


def test_base_prompt_readable():
    """包内基础提示词存在且非空(资源打包生效)。"""
    prompt = read_base_prompt()
    assert len(prompt) > 100
    assert "codeagent" in prompt


def test_candidates_include_claude_compat():
    """候选表兼容 Claude 生态(AGENTS.override > AGENTS > CLAUDE)。"""
    assert AGENTS_CANDIDATES == (
        "AGENTS.override.md",
        "AGENTS.md",
        "AGENTS.MD",
        "CLAUDE.md",
        "CLAUDE.MD",
    )
