"""app/context/agents.py:分层上下文文件(AGENTS.md)加载器与 system prompt 合并(纯函数)。

语义对齐 Pi(`earendil-works/pi` 的 ``loadProjectContextFiles``,2026-08-15 源码实查):
- ``load_agents_files(cwd, config_dir)``:全局(``<config_dir>/AGENTS.md``)优先,
  随后从 cwd **向上遍历到文件系统根**(非 git 根,自包含可离线测),每级目录
  按候选表取第一个存在的文件;顺序 = 全局最前,越近 cwd 越靠后(优先级越高);
  按绝对路径去重;单个文件读失败跳过(不中断加载);
- 候选表:``AGENTS.override.md > AGENTS.md > AGENTS.MD > CLAUDE.md > CLAUDE.MD``
  (兼容 Claude 生态,项目自身即有 CLAUDE.md);
- ``build_system_prompt(base, agents_files)``:Pi 式合并——基础提示词 +
  ``<project_context>`` 段,每个文件包 ``<project_instructions path="...">``
  来源标注(FR-8.4 来源透明);
- ``read_base_prompt()``:经 importlib.resources 读包内基础提示词
  (``resources/prompts/system.md``;延迟到调用,模块顶层零副作用)。

分层约束:本模块仅标准库 + 文件系统,不 import core/session/ai/tools
(test_decoupling 对 app/ 层的强制);``config_dir`` 由调用方(组合根)注入。
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

__all__ = [
    "AGENTS_CANDIDATES",
    "build_system_prompt",
    "load_agents_files",
    "read_base_prompt",
]

#: 每级目录的候选文件名(按优先级;兼容 Claude 生态)。
AGENTS_CANDIDATES: tuple[str, ...] = (
    "AGENTS.override.md",
    "AGENTS.md",
    "AGENTS.MD",
    "CLAUDE.md",
    "CLAUDE.MD",
)


def _first_candidate(directory: Path) -> Path | None:
    """目录内按候选表取第一个存在的文件(目录项跳过)。"""
    for name in AGENTS_CANDIDATES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def load_agents_files(cwd: str | Path, config_dir: str | Path) -> list[tuple[str, str]]:
    """分层加载上下文文件,返回 ``[(绝对路径, 内容), ...]``(全局先、近者后)。"""
    resolved_cwd = Path(cwd).expanduser().resolve()
    resolved_config = Path(config_dir).expanduser().resolve()

    files_list: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(candidate: Path | None) -> None:
        if candidate is None:
            return
        path = str(candidate.resolve())
        if path in seen:
            return
        seen.add(path)
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError:
            return  # 读失败跳过,不中断加载
        files_list.append((path, content))

    # ① 全局(用户级)
    add(_first_candidate(resolved_config))
    # ② cwd 向上收集祖先目录,再按 根 → … → cwd 顺序加载——越近 cwd 越靠后
    #    (优先级越高;对齐 Pi 的 unshift 行为,2026-08-15 源码实查)。
    ancestors: list[Path] = []
    current = resolved_cwd
    while True:
        ancestors.append(current)
        if current.parent == current:
            break
        current = current.parent
    for directory in reversed(ancestors):  # 根 → cwd
        add(_first_candidate(directory))
    return files_list


def build_system_prompt(base: str, agents_files: list[tuple[str, str]]) -> str:
    """合并基础提示词与分层上下文文件(Pi 式 ``<project_instructions>`` 段)。

    - 每个文件内容以 ``path`` 绝对路径标注来源(FR-8.4);
    - 无上下文文件时仅返回基础提示词(不产生空 ``<project_context>`` 段)。
    """
    if not agents_files:
        return base
    sections = [f"<project_instructions path=\"{path}\">\n{content}\n</project_instructions>"
                for path, content in agents_files]
    context = "<project_context>\nProject-specific instructions and guidelines:\n\n" \
        + "\n\n".join(sections) + "\n</project_context>"
    return f"{base}\n\n{context}"


def read_base_prompt() -> str:
    """读取包内基础系统提示词(``resources/prompts/system.md``)。"""
    return files("codeagent.resources").joinpath("prompts", "system.md").read_text(
        encoding="utf-8"
    )
