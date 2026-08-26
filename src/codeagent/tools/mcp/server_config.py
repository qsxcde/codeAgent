"""MCP server 启动配置解析。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class McpServerSpec:
    """一个 MCP server 的 stdio 启动声明。"""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


def parse_mcp_config(config_dir: str | Path) -> tuple[list[McpServerSpec], list[str]]:
    """解析用户级 ``mcp.json``，返回 server 声明与诊断信息。"""
    path = Path(config_dir).expanduser() / "mcp.json"
    if not path.is_file():
        return [], []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"parse_failed: MCP 配置解析失败 {path}: {exc}"]

    servers: list[McpServerSpec] = []
    diagnostics: list[str] = []
    entries = raw.get("servers", []) if isinstance(raw, dict) else None
    if entries is None or not isinstance(entries, list):
        return [], [f"invalid_metadata: MCP 配置缺少 servers 列表: {path}"]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            diagnostics.append(f"invalid_metadata: MCP 配置第 {index + 1} 项不是对象")
            continue
        name = entry.get("name")
        command = entry.get("command")
        if not isinstance(name, str) or not name.strip():
            diagnostics.append(f"invalid_metadata: MCP 配置第 {index + 1} 项缺少 name")
            continue
        if not isinstance(command, str) or not command.strip():
            diagnostics.append(f"invalid_metadata: MCP server '{name}' 缺少 command")
            continue
        args = entry.get("args", [])
        env = entry.get("env", {})
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            diagnostics.append(f"invalid_metadata: MCP server '{name}' 的 args 非法")
            continue
        if not isinstance(env, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in env.items()
        ):
            diagnostics.append(f"invalid_metadata: MCP server '{name}' 的 env 非法")
            continue
        servers.append(
            McpServerSpec(
                name=name.strip(),
                command=command.strip(),
                args=tuple(args),
                env=dict(env),
            )
        )
    return servers, diagnostics


__all__ = ["McpServerSpec", "parse_mcp_config"]
