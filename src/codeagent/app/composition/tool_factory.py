"""内建工具和 MCP 工具的组合根装配。"""

from __future__ import annotations

from typing import Any


def create_tools(cfg: Any = None, skills: dict[str, str] | None = None) -> list[Any]:
    """装配内建原子工具，并注入 Skill 渲染注册表。"""
    from codeagent.tools.registry import make_tools

    return make_tools(cfg, skills=skills)


def _load_mcp_tools(cfg: Any = None) -> tuple[list[Any], list[str]]:
    """加载 MCP 工具及诊断信息。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.tools.mcp.loader import load_mcp_tools

    return load_mcp_tools(CONFIG_DIR)

