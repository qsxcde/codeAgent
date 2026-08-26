"""MCP 工具权限规则解析与匹配。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class McpPermissionRules:
    """三级 MCP 权限规则：deny > ask > allow。"""

    deny: tuple[str, ...] = ()
    ask: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "McpPermissionRules":
        return cls()

    def decide(self, qualified_name: str) -> str | None:
        normalized = _normalize(qualified_name)
        for action in ("deny", "ask", "allow"):
            if any(
                _match_rule(normalized, _normalize(rule))
                for rule in getattr(self, action)
            ):
                return action
        return None


def _normalize(text: str) -> str:
    return text.strip().lower().replace("-", "_").replace(".", "_")


def _match_rule(name: str, rule: str) -> bool:
    if rule == "mcp__*":
        return name.startswith("mcp__")
    if rule.endswith("__*"):
        prefix = rule[:-3]
        return name.startswith(prefix + "__")
    if rule.count("__") == 1:
        return name.startswith(rule + "__")
    return name == rule


def parse_mcp_permissions(config_dir: str | Path) -> McpPermissionRules:
    """读取 ``mcp.json`` 中的 permissions；缺失或非法时返回空规则。"""
    path = Path(config_dir).expanduser() / "mcp.json"
    if not path.is_file():
        return McpPermissionRules.empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return McpPermissionRules.empty()
    permissions = raw.get("permissions", {}) if isinstance(raw, dict) else {}
    if not isinstance(permissions, dict):
        return McpPermissionRules.empty()
    rules: dict[str, tuple[str, ...]] = {}
    for action in ("deny", "ask", "allow"):
        entries = permissions.get(action, [])
        if not isinstance(entries, list):
            continue
        rules[action] = tuple(
            entry for entry in entries if isinstance(entry, str) and entry.strip()
        )
    return McpPermissionRules(
        deny=rules.get("deny", ()),
        ask=rules.get("ask", ()),
        allow=rules.get("allow", ()),
    )


__all__ = ["McpPermissionRules", "parse_mcp_permissions"]
