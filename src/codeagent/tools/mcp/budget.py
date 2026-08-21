"""tools/mcp/budget.py:MCP 工具分组预算(纯函数,离线可测)。

mcp spec「分组预算」:全局工具数上限 + 每 server 上限 + 描述长度上限,
超限工具被裁剪且**产生可见诊断**(Qwen 2 连接硬限的用户反噬教训:裁剪必须
可见、可解释,不静默丢弃);内建工具不参与预算(恒保留)。

分层约束:tools 层,仅标准库,不 import core/session/ai/app。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "GLOBAL_TOOL_CAP",
    "PER_SERVER_TOOL_CAP",
    "DESCRIPTION_CAP",
    "apply_budget",
    "truncate_description",
]

#: 全局 MCP 工具数上限(可配置默认值)。
GLOBAL_TOOL_CAP = 40
#: 每 server 工具数上限。
PER_SERVER_TOOL_CAP = 15
#: 工具描述长度上限(提示词膨胀的主要来源是描述,不是数量)。
DESCRIPTION_CAP = 200


def truncate_description(description: str, cap: int = DESCRIPTION_CAP) -> str:
    """描述截断并标记(截断前缀省略号,标注原文长度)。"""
    if len(description) <= cap:
        return description
    return f"{description[: cap - 10]}…({len(description)} 字符,已截断)"


def apply_budget(
    tools_by_server: dict[str, list[Any]],
    *,
    global_cap: int = GLOBAL_TOOL_CAP,
    per_server_cap: int = PER_SERVER_TOOL_CAP,
    desc_cap: int = DESCRIPTION_CAP,
) -> tuple[list[Any], list[str]]:
    """按分组预算裁剪 MCP 工具,返回 (保留工具, 诊断消息列表)。

    - 裁剪确定性:按 server 配置顺序 + 工具列表顺序;
    - 每 server 超限 → 裁掉尾部,诊断列出被裁者;
    - 总量超限 → 从最后的 server 起裁(逆序释放),诊断列出;
    - 保留工具的描述经 ``truncate_description`` 截断。
    """
    kept: list[Any] = []
    diagnostics: list[str] = []
    for server_name, tools in tools_by_server.items():
        if len(tools) > per_server_cap:
            dropped = tools[per_server_cap:]
            tools = tools[:per_server_cap]
            diagnostics.append(
                f"dropped: MCP server '{server_name}' 工具超限"
                f"({len(dropped) + per_server_cap} > {per_server_cap}),裁剪: "
                + ", ".join(t.name for t in dropped)
            )
        kept.extend(tools)
    # 总量超限:逆序逐 server 释放,直到不超过上限。
    while len(kept) > global_cap:
        released = kept.pop()
        diagnostics.append(
            f"dropped: MCP 工具总量超限({len(kept) + 1} > {global_cap}),裁剪: {released.name}"
        )
    for tool in kept:
        tool.description = truncate_description(tool.description, desc_cap)
    return kept, diagnostics
