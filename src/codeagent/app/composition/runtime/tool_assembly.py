"""Tool loading and profile filtering for runtime configuration."""

from __future__ import annotations

import atexit
from collections.abc import Iterable
from typing import Any

from codeagent.tools.shared import ToolResourceLimits

from ..tools.adapter import adapt_tools
from ..tools.factory import _load_mcp_tools, create_tools


def assemble_runtime_tools(
    cfg: Any,
    skills: list[Any],
    resource_limits: ToolResourceLimits,
    mcp_diagnostics: list[str] | None,
    allowed_tool_names: Iterable[str] | None,
    subagent_runner: Any,
) -> tuple[list[Any], list[Any]]:
    """Load, adapt and optionally restrict concrete tools for one runtime."""
    from codeagent.app.skills.prompt import format_skill_invocation
    from codeagent.tools.mcp.loader import close_mcp_tools

    rendered_skills = {skill.name: format_skill_invocation(skill) for skill in skills}
    mcp_tools, mcp_diags = _load_mcp_tools(cfg)
    if mcp_diagnostics is not None:
        mcp_diagnostics.extend(mcp_diags)
    if mcp_tools:
        atexit.register(close_mcp_tools, mcp_tools)
    raw_tools = create_tools(
        cfg, skills=rendered_skills, resource_limits=resource_limits
    ) + mcp_tools
    tools = adapt_tools(raw_tools)
    if allowed_tool_names is not None:
        allowed = frozenset(allowed_tool_names)
        tools = [tool for tool in tools if tool.name in allowed]
    if subagent_runner is not None:
        from codeagent.app.composition.subagent.delegate_tool import DelegateTool

        tools.append(DelegateTool(subagent_runner))
    return tools, mcp_tools


__all__ = ["assemble_runtime_tools"]
