"""tools/mcp/config.py:MCP server 配置解析(纯函数,离线可测)。

配置来源 **仅用户级** ``<config_dir>/mcp.json``(mcp spec「配置与信任边界」):
- 仓库内项目级 ``.mcp.json`` 不被加载(仓库引导启动任意外部进程是恶意向量);
- 文件缺失 / 为空 → 空 server 列表,不报错;
- 结构错误 → 诊断(``parse_failed``)+ 跳过该文件/该条目,不中断。

分层约束:tools 层,仅标准库 + 本包,不 import core/session/ai/app。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "McpPermissionRules",
    "McpServerSpec",
    "parse_mcp_config",
    "parse_mcp_permissions",
]


@dataclass(frozen=True)
class McpServerSpec:
    """一个 MCP server 的启动声明(stdio 形态)。"""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class McpPermissionRules:
    """MCP 工具权限规则(CodeBuddy 式三级 deny/ask/allow + 通配)。

    - 规则命中优先级:**deny > ask > allow**(deny 最高,ask 覆盖 allow);
    - 规则形态(限定名 ``mcp__<server>__<tool>``):
      ``mcp__*``(全部,仅 deny/ask 有意义)、``mcp__<server>`` 或
      ``mcp__<server>__*``(server 级)、``mcp__<server>__<tool>``(工具级);
    - 比较不区分大小写,连字符/点按下划线归一;
    - ``decide`` 返回 None = 未命中(调用方按默认放行——用户级配置即信任)。
    """

    deny: tuple[str, ...] = ()
    ask: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "McpPermissionRules":
        return cls()

    def decide(self, qualified_name: str) -> str | None:
        """对限定名返回命中动作(deny/ask/allow);未命中返回 None。"""
        normalized = _normalize(qualified_name)
        for action in ("deny", "ask", "allow"):
            if any(_match_rule(normalized, _normalize(rule)) for rule in getattr(self, action)):
                return action
        return None


def _normalize(text: str) -> str:
    """规则/名称归一:小写、连字符与点按下划线。"""
    return text.strip().lower().replace("-", "_").replace(".", "_")


def _match_rule(name: str, rule: str) -> bool:
    """限定名与规则匹配(``*`` 仅作为末段通配)。

    - ``mcp__<server>``(无工具段):server 级,匹配该 server 全部工具;
    - ``mcp__<server>__*``:显式 server 级通配(同上一形态);
    - ``mcp__<server>__<tool>``:工具级精确匹配。
    """
    if rule == "mcp__*":
        return name.startswith("mcp__")
    if rule.endswith("__*"):
        prefix = rule[:-3]  # 去掉尾部 "__*"(3 字符)
        return name.startswith(prefix + "__")
    if rule.count("__") == 1:  # server 级(无工具段)
        return name.startswith(rule + "__")
    return name == rule


def parse_mcp_config(
    config_dir: str | Path,
) -> tuple[list[McpServerSpec], list[str]]:
    """解析 ``<config_dir>/mcp.json``,返回 (servers, 诊断消息列表)。

    - 文件不存在 → (空, 空):无 MCP 工具是常态,不产生诊断;
    - JSON 解析失败 / 结构非法 → 诊断 + 跳过该文件;
    - 条目缺 name/command 或类型非法 → 诊断 + 跳过该条目。
    """
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
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            diagnostics.append(f"invalid_metadata: MCP server '{name}' 的 args 非法")
            continue
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
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


def parse_mcp_permissions(config_dir: str | Path) -> McpPermissionRules:
    """从 ``mcp.json`` 解析权限规则(``permissions.allow/ask/deny`` 字符串列表)。

    - 文件缺失 / 无 permissions 段 / 结构非法 → 空规则(默认全部放行);
    - 非法条目(非字符串)跳过,不产生诊断(权限是渐进增强配置)。
    """
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
