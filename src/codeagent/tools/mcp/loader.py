"""tools/mcp/loader.py:MCP 工具装配入口——配置 → 启动 → 适配 → 预算。

mcp spec「装配失败语义与可见性」:server 启动/初始化/工具列表失败 → 诊断 +
跳过该 server,不中断整体装配;成功者进入工具列表并受分组预算约束。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeagent.tools.mcp.adapter import McpTool
from codeagent.tools.mcp.budget import apply_budget
from codeagent.tools.mcp.client import McpServerClient
from codeagent.tools.mcp.config import parse_mcp_config

__all__ = ["load_mcp_tools", "close_mcp_tools", "close_mcp_clients"]

#: 单 server 装配超时(启动 + initialize + tools/list)。
SERVER_START_TIMEOUT = 10.0


def close_mcp_tools(tools: list[Any]) -> None:
    """关闭工具集合涉及的全部 MCP server 客户端(幂等;atexit 兜底用)。

    同一 client 被多个工具共享(每 server 一个 client),按 client 去重关闭。
    """
    seen: set[int] = set()
    for tool in tools:
        client = getattr(tool, "client", None)
        if client is None or id(client) in seen:
            continue
        seen.add(id(client))
        client.close()


def close_mcp_clients(clients: list[Any]) -> None:
    """Close a client collection directly, deduplicated and idempotently."""
    seen: set[int] = set()
    for client in clients:
        if client is None or id(client) in seen:
            continue
        seen.add(id(client))
        close = getattr(client, "close", None)
        if callable(close):
            close()


def load_mcp_tools(
    config_dir: str | Path,
    *,
    tool_timeout: float | None = None,
) -> tuple[list[Any], list[str]]:
    """装配全部 MCP 工具,返回 (工具列表, 诊断消息列表)。

    - 配置缺失/为空 → 空列表(常态,无诊断);
    - 逐 server:启动失败 → 诊断 + 跳过(不中断其余 server 与内建工具);
    - 成功者经 ``apply_budget`` 分组预算(全局/每 server/描述三上限);
    - 工具名 ``{server}:{tool}``,调用超时取会话 ``tool_timeout``。
    """
    servers, config_diags = parse_mcp_config(config_dir)
    tools_by_server: dict[str, list[Any]] = {}
    clients: list[McpServerClient] = []
    diagnostics: list[str] = list(config_diags)
    for spec in servers:
        client = McpServerClient(spec.name, spec)  # McpServerSpec 兼容 StdioServerParameters
        clients.append(client)
        try:
            client.start(timeout=SERVER_START_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - 单 server 失败不中断装配
            diagnostics.append(f"start_failed: MCP server '{spec.name}' 启动失败: {exc}")
            client.close()
            continue
        tools = [
            McpTool(client, info, timeout=tool_timeout) for info in client.tools
        ]
        tools_by_server[spec.name] = tools
    kept, budget_diags = apply_budget(tools_by_server)
    diagnostics.extend(budget_diags)
    kept_clients = {id(getattr(tool, "client", None)) for tool in kept}
    close_mcp_clients([client for client in clients if id(client) not in kept_clients])
    return kept, diagnostics
