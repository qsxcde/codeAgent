"""JSONL record codecs and format validation for session storage."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from codeagent.core.messages import Message, ToolCall
from codeagent.session.store_models import CURRENT_VERSION

TITLE_MAX = 20

def _now() -> str:
    """ISO 本地时间(毫秒精度,保证同秒创建的会话列表排序稳定)。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"


def _derive_title(name: str, first_user_content: str) -> str:
    """标题派生(design D3):显式命名优先,否则首条用户消息截断。

    截断只按字符数,不做语义切分——标题仅用于列表展示。
    """
    if name:
        return name
    text = " ".join(first_user_content.split())
    if not text:
        return ""
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX] + "…"


def _message_to_dict(m: Message) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": "message",
        "id": m.id,
        "parentId": m.parent_id,
        "role": m.role,
        "content": m.content,
    }
    if m.tool_calls:
        d["tool_calls"] = [
            {"id": c.id, "name": c.name, "args": c.args} for c in m.tool_calls
        ]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    return d


def _dict_to_message(d: dict[str, Any]) -> Message:
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        tool_calls=[
            ToolCall(id=c["id"], name=c["name"], args=c.get("args", {}))
            for c in d.get("tool_calls", [])
        ],
        tool_call_id=d.get("tool_call_id", ""),
        id=d.get("id", ""),
        parent_id=d.get("parentId"),
    )


def _validate_header(entry: dict[str, Any], path: Path) -> None:
    """header 校验:首 entry 必须是 session 且版本兼容(格式 v1)。"""
    if entry.get("type") != "session":
        raise ValueError(f"会话文件缺少 header: {path}")
    version = entry.get("version")
    if version != CURRENT_VERSION:
        raise ValueError(
            f"会话文件版本不兼容 {path}: version={version}, 期望 {CURRENT_VERSION}"
        )

