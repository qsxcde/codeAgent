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
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Message",
    "ToolCall",
    "ToolResult",
    "ToolExecutionStatus",
    "parse_tool_arguments",
    "new_id",
    "remove_by_id",
    "replace_or_append",
    "attach_tool_results",
]


class ToolExecutionStatus:
    """Stable runtime status values shared by core, tools and subscribers."""

    OK = "ok"
    INVALID_ARGUMENTS = "invalid_arguments"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    CLEANUP_UNCERTAIN = "cleanup_uncertain"
    ALL = (
        OK,
        INVALID_ARGUMENTS,
        FAILED,
        REJECTED,
        TIMED_OUT,
        CANCELLED,
        CLEANUP_UNCERTAIN,
    )


def parse_tool_arguments(
    raw: Any,
    *,
    finish_reason: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Normalize provider tool arguments and return ``(args, error)``.

    Providers are inconsistent about whether arguments arrive as a JSON string
    or an already decoded mapping.  Invalid/non-object values are represented
    by an empty object solely for wire compatibility; the error marker prevents
    the executor from invoking the real tool.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, None
    if isinstance(raw, dict):
        return dict(raw), None
    if not isinstance(raw, str):
        return {}, "工具参数必须是 JSON 对象"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        suffix = "(可能因响应截断)" if finish_reason == "length" else ""
        return {}, f"工具参数 JSON 无效{suffix}: {exc.msg} (位置 {exc.pos})"
    if not isinstance(value, dict):
        return {}, f"工具参数必须是 JSON 对象,实际为 {type(value).__name__}"
    return value, None


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
    #: Runtime-only parse diagnostic.  It is deliberately omitted from JSONL.
    argument_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"id": self.id, "name": self.name, "args": self.args, "type": "tool_call"}
        if self.argument_error:
            result["argument_error"] = self.argument_error
        return result


@dataclass
class ToolResult:
    """一次工具执行结果(含错误标记,供事件 metadata 透传)。

    - ``rejected``:经安全策略/用户确认被拒绝(security-permissions),结果
      内容为拒绝原因;订阅方(TUI)据此渲染「已拒绝」状态。
    """

    tool_call_id: str
    content: str
    error: bool = False
    name: str = ""
    rejected: bool = False
    status: str = ""
    operation_id: str = ""
    cleanup_confirmed: bool | None = None
    #: 运行时输出统计，不参与 Message JSONL 持久化。
    total_bytes: int = 0
    total_lines: int = 0
    shown_lines: int = 0
    truncated_by: str | None = None
    artifact_path: str | None = None

    def __post_init__(self) -> None:
        if not self.status:
            if self.rejected:
                self.status = ToolExecutionStatus.REJECTED
            elif self.error:
                self.status = ToolExecutionStatus.FAILED
            else:
                self.status = ToolExecutionStatus.OK
        if not self.total_bytes:
            self.total_bytes = len(self.content.encode("utf-8"))
        if not self.total_lines:
            self.total_lines = len(self.content.splitlines())
        if not self.shown_lines:
            self.shown_lines = self.total_lines
        if self.truncated_by is None and re.search(
            r"(?:输出)?已截断|达到(?:字节|行数)?上限|条目超限", self.content
        ):
            self.truncated_by = "tool"
        marker = re.search(r"\[(\d+)-(\d+)/(\d+)\s*行\]", self.content)
        if marker is not None and int(marker.group(2)) < int(marker.group(3)):
            self.shown_lines = int(marker.group(2))
            self.total_lines = int(marker.group(3))
            self.truncated_by = self.truncated_by or "tool"
        item_marker = re.search(
            r"仅显示前\s*(\d+)\s*条.*?共\s*(\d+)\s*条", self.content
        )
        if item_marker is not None:
            self.shown_lines = int(item_marker.group(1))
            self.total_lines = int(item_marker.group(2))
            self.truncated_by = self.truncated_by or "tool"


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
