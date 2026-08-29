"""内建工具和 MCP 工具的组合根装配。"""

from __future__ import annotations

from typing import Any

from codeagent.tools.shared import ToolResourceLimits


def resolve_tool_resource_limits(
    cfg: Any = None,
    explicit: ToolResourceLimits | None = None,
) -> ToolResourceLimits:
    """在组合根解析一次工具资源边界，供所有运行时端口共享。"""
    if explicit is not None:
        return explicit
    if cfg is None:
        from codeagent.app.config import Settings

        cfg = Settings()
    return ToolResourceLimits.from_config(cfg)


def create_tools(
    cfg: Any = None,
    skills: dict[str, str] | None = None,
    resource_limits: ToolResourceLimits | None = None,
) -> list[Any]:
    """装配内建原子工具，并注入 Skill 渲染注册表。"""
    from codeagent.tools.registry import make_tools

    return make_tools(
        cfg,
        skills=skills,
        resource_limits=resolve_tool_resource_limits(cfg, resource_limits),
    )


def _load_mcp_tools(cfg: Any = None) -> tuple[list[Any], list[str]]:
    """加载 MCP 工具及诊断信息。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.tools.mcp.loader import load_mcp_tools

    return load_mcp_tools(CONFIG_DIR)
