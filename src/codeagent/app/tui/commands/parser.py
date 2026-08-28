"""app/tui/commands.py:斜杠命令注册表与解析(纯函数,离线可测)。

设计(design D2,T-44;session-fork 改写):
- ``parse(text)`` 把输入解析为 ``Literal | Command | UnknownCommand`` 三类:
  ``//`` 起始按字面量发送(去掉一个 ``/``,不触发命令解析);普通文本原样;
- 注册表声明命令名 / 说明 / 位置参数 / 是否已接线(``available``):
  ``/fork`` 从指定 user 消息分叉会话(T-42,session-fork 落地);
- 本模块零副作用、不 import session/ai/tools;命令动作闭包由视图层分派
  (manager 经组合根注入),解析层只回答"这条输入是什么"。

分层约束:app/tui 层,禁止 import textual/具体引擎;样式无关(不依赖 theme)。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "CommandSpec",
    "Command",
    "UnknownCommand",
    "Literal",
    "parse",
    "default_registry",
    "help_text",
]


@dataclass(frozen=True)
class CommandSpec:
    """注册表中的一条命令声明。"""

    name: str
    summary: str
    args: tuple[str, ...] = ()
    available: bool = True  # False = 已注册但依赖其它阶段,提示未可用
    picker: bool = False  # True = 无参执行时打开选择面板(provider/model/effort)


@dataclass(frozen=True)
class Command:
    """命中的命令(含参数)。"""

    name: str
    args: tuple[str, ...] = ()
    raw_args: str = ""


@dataclass(frozen=True)
class UnknownCommand:
    """未注册的命令(供视图给出可操作提示)。"""

    name: str


@dataclass(frozen=True)
class Literal:
    """字面量输入(``//`` 转义已去除一个 ``/``;普通文本原样)。"""

    text: str


def parse(text: str, registry: Mapping[str, CommandSpec]) -> Command | UnknownCommand | Literal:
    """把输入框文本解析为命令或字面量(纯函数,不查状态)。

    - ``//`` 前缀 → 字面量(去掉一个 ``/``,不触发命令解析);
    - 非 ``/`` 起始或单独 ``/`` → 字面量原样;
    - ``/name args`` → 注册命中 ``Command``;未注册 → ``UnknownCommand``。
    """
    if text.startswith("//"):
        return Literal(text[1:])
    if not text.startswith("/"):
        return Literal(text)
    name, _, raw_args = text[1:].partition(" ")
    name = name.strip()
    if not name:
        return Literal(text)
    spec = registry.get(name)
    if spec is None:
        return UnknownCommand(name)
    return Command(name, tuple(raw_args.split()), raw_args.strip())


def default_registry() -> dict[str, CommandSpec]:
    """v0.2 阶段 5 命令表(T-44);``/fork`` 自 session-fork 落地(T-42 改写)。"""
    return {
        "help": CommandSpec("help", "显示命令帮助"),
        "ask": CommandSpec("ask", "以只读问答模式发送消息", args=("text...",)),
        "plan": CommandSpec("plan", "以只读规划模式发送消息", args=("text...",)),
        "code": CommandSpec("code", "以代码模式发送消息", args=("text...",)),
        "mode": CommandSpec(
            "mode", "设置粘性模式(ask/plan/code/auto)", args=("mode",)
        ),
        "clear": CommandSpec("clear", "清空聊天区"),
        "status": CommandSpec("status", "显示会话状态"),
        "sessions": CommandSpec(
            "sessions",
            "列出 / 新建 / 切换 / 恢复会话(recent = 最近)",
            args=("action",),
            picker=True,
        ),
        "tree": CommandSpec("tree", "展示会话 fork 链树(/tree <id> 切换)", args=("session-id",)),
        "tools": CommandSpec("tools", "列出可用工具"),
        "provider": CommandSpec("provider", "切换 provider", args=("name",), picker=True),
        "login": CommandSpec(
            "login", "配置 provider 的 API key 并切换", args=("provider",), picker=True
        ),
        "model": CommandSpec(
            "model", "切换模型(支持 model:effort)", args=("model",), picker=True
        ),
        "effort": CommandSpec("effort", "切换思考强度", args=("level",), picker=True),
        "fork": CommandSpec(
            "fork", "从指定消息分叉会话(缺省最近用户消息)", args=("message-id",)
        ),
        "compact": CommandSpec("compact", "压缩当前会话上下文"),
        "output": CommandSpec(
            "output", "浏览或导出最近工具输出", args=("action", "args..."),
        ),
        "retry": CommandSpec("retry", "安全重试最近一次模型失败"),
        "continue": CommandSpec("continue", "在失败回合后继续新的消息", args=("text...",)),
        "skills": CommandSpec(
            "skills",
            "列出/加载技能或管理 Package(install/list/update/remove/reload)",
            args=("action", "args..."),
        ),
        "mcp": CommandSpec("mcp", "列出 MCP server 与工具(含诊断)"),
        "quit": CommandSpec("quit", "退出 TUI(等同 Ctrl+C)"),
    }


def help_text(registry: Mapping[str, CommandSpec]) -> str:
    """``/help`` 全文帮助(只读命令,纯函数)。"""
    lines = ["可用命令:"]
    for spec in sorted(registry.values(), key=lambda s: s.name):
        suffix = "" if spec.available else " (未可用)"
        lines.append(f"  /{spec.name} — {spec.summary}{suffix}")
    return "\n".join(lines)
