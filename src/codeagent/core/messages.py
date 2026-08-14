"""core/messages.py:自研消息模型与归约(替代 langgraph add_messages)。

归约语义与 langgraph 真实行为对齐(源码核实,2026-08-14,见迭代记录):
- 按 id 去重/替换(同 id 消息覆盖旧消息);
- 按 id 删除(RemoveMessage 等价,失败回滚 / 压缩复用);
- 工具结果归属**靠写入顺序**(ReAct 串行 + 并行 gather 保序),不做插入扫描;
- 不存在"相邻同 role 消息合并"(v0.1 文档描述不实,随本模块落地勘误)。

消息 id 用 **uuid7**(48 位毫秒时间戳 + 版本/variant + 62 位随机):时间有序、
全局唯一,服务 JSONL 树形排序与按 id 删除/归属/恢复。

分层约束:core 不 import config / ai / tools / session,本模块仅依赖标准库。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Message",
    "ToolCall",
    "ToolResult",
    "new_id",
    "remove_by_id",
    "replace_or_append",
    "attach_tool_results",
]


def new_id() -> str:
    """uuid7:时间有序、全局唯一(手写,不引三方依赖)。

    布局(RFC 9562):48 位 unix 毫秒时间戳 + 4 位版本(7)+ 2 位 variant(10)
    + 62 位随机。同一毫秒内多次调用不保证严格递增(随机位保证唯一),
    跨毫秒严格有序——JSONL 树形按 id 排序即按时间排序。
    """
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ts_ms << 80) | (0x7 << 76) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    h = f"{value:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


@dataclass
class ToolCall:
    """一次工具调用(core 自有类型;组合根适配器负责与模型协议互转)。"""

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "args": self.args, "type": "tool_call"}


@dataclass
class ToolResult:
    """一次工具执行结果(含错误标记,供事件 metadata 透传)。"""

    tool_call_id: str
    content: str
    error: bool = False
    name: str = ""


@dataclass
class Message:
    """一条对话消息(自研,替代 langchain BaseMessage)。

    - ``role``:``user`` / ``assistant`` / ``tool``;
    - ``tool_calls``:assistant 消息携带的工具调用(无则为空列表);
    - ``tool_call_id``:tool 消息归属的调用 id;
    - ``id``:uuid7,构造时自动分配(可显式传入,如恢复时);
    - ``parent_id``:JSONL 树形的父级 id(同会话内直接前驱)。
    """

    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    id: str = ""
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()


def remove_by_id(messages: list[Message], ids: set[str]) -> list[Message]:
    """按 id 删除(RemoveMessage 等价):返回新列表,不修改入参。"""
    return [m for m in messages if m.id not in ids]


def replace_or_append(messages: list[Message], msg: Message) -> None:
    """同 id 消息原地替换,否则追加(归约语义①)。"""
    for i, existing in enumerate(messages):
        if existing.id == msg.id:
            messages[i] = msg
            return
    messages.append(msg)


def attach_tool_results(messages: list[Message], results: list[ToolResult]) -> None:
    """把工具结果按 tool_call_id 归属到对应 assistant 之后(归约语义②)。

    实现依赖写入顺序:遍历现有消息,遇到带 tool_calls 的 assistant 时按
    ``tool_calls`` 列表序追加对应结果(并行 gather 保序,与 v0.1 一致);
    未归属的 id(防御:调用列表里没有)追加到列表尾部。
    """
    pending = {r.tool_call_id: r for r in results}
    appended: list[Message] = []
    for m in messages:
        if m.tool_calls:
            for call in m.tool_calls:
                result = pending.pop(call.id, None)
                if result is not None:
                    appended.append(
                        Message(
                            role="tool",
                            content=result.content,
                            tool_call_id=call.id,
                            parent_id=m.id,
                        )
                    )
    for result in pending.values():
        appended.append(
            Message(role="tool", content=result.content, tool_call_id=result.tool_call_id)
        )
    messages.extend(appended)
