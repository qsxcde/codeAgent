"""Shared helpers for split behavior tests."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from codeagent.core.messages import Message, ToolCall
from codeagent.session.store import (
    CURRENT_VERSION,
    CompactionEntry,
    JsonFileStore,
    MemoryStore,
)

def _store(tmp_path):
    return JsonFileStore(tmp_path / "sessions")


def _fill_session(store, session_id: str) -> list[Message]:
    """写入 user → assistant → user → assistant 消息链,返回消息列表。"""
    store.create(session_id, model="deepseek-v4-flash", effort="high")
    m1 = Message(role="user", content="第一问")
    m2 = Message(role="assistant", content="第一答", parent_id=m1.id)
    m3 = Message(role="user", content="第二问", parent_id=m2.id)
    m4 = Message(role="assistant", content="第二答", parent_id=m3.id)
    for m in (m1, m2, m3, m4):
        store.append_message(session_id, m)
    return [m1, m2, m3, m4]


def _usage_dict(input_tokens=0, output_tokens=0, reasoning_tokens=0, cached_tokens=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
    }


__all__ = [name for name in globals() if not name.startswith("__")]
