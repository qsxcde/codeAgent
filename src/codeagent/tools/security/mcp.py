"""MCP 工具权限分类。"""

from __future__ import annotations

from typing import Any

from codeagent.tools.security.decision import ALLOW, ASK, DENY, SecurityDecision


def classify_mcp(tool_name: str, rules: Any) -> SecurityDecision:
    decision = rules.decide(tool_name) if rules is not None else None
    if decision == "deny":
        return SecurityDecision(DENY, f"MCP 权限规则拒绝: {tool_name}")
    if decision == "ask":
        return SecurityDecision(ASK, f"MCP 工具调用需确认: {tool_name}")
    return SecurityDecision(ALLOW)


__all__ = ["classify_mcp"]
