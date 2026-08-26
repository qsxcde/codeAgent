"""MCP 配置公共兼容入口。

具体职责位于 ``server_config`` 与 ``permissions``；此模块仅保持现有导入
路径，避免配置调用方同时迁移造成无关变更。
"""

from codeagent.tools.mcp.permissions import McpPermissionRules, parse_mcp_permissions
from codeagent.tools.mcp.server_config import McpServerSpec, parse_mcp_config

__all__ = [
    "McpPermissionRules",
    "McpServerSpec",
    "parse_mcp_config",
    "parse_mcp_permissions",
]
