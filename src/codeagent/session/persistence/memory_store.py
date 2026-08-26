"""In-memory session store used by tests and one-shot runs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from codeagent.core.messages import Message
from codeagent.session.persistence.codec import _derive_title, _now
from codeagent.session.persistence.models import (
    CompactionEntry,
    CompactionState,
    SessionRef,
    UsageStats,
)

class MemoryStore:
    """内存后端(测试 / 一次性 headless 用),零文件系统依赖。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRef] = {}
        self._messages: dict[str, list[Message]] = {}
        self._compactions: list[tuple[str, CompactionEntry]] = []
        self._meta: dict[str, dict[str, Any]] = {}
        self._usage: dict[str, UsageStats] = {}

    def create(
        self,
        session_id: str,
        *,
        parent_session: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> SessionRef:
        if session_id in self._sessions:
            raise ValueError(f"会话已存在: {session_id}")
        ref = SessionRef(
            id=session_id,
            timestamp=_now(),
            cwd=cwd or str(Path.cwd()),
            parent_session=parent_session,
            model=model or "",
            effort=effort or "",
        )
        self._sessions[session_id] = ref
        self._messages[session_id] = []
        return ref

    def get(self, session_id: str) -> SessionRef | None:
        if session_id not in self._sessions:
            return None
        return self._ref_with_title(session_id)

    def list(self) -> list[SessionRef]:
        refs = [self._ref_with_title(sid) for sid in self._sessions]
        refs.sort(key=lambda r: (r.timestamp, r.id))
        return refs

    def load_messages(self, session_id: str) -> list[Message]:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        return list(self._messages[session_id])

    def load_context(self, session_id: str) -> CompactionState:
        """重构压缩后的上下文(内存后端,与文件后端同语义)。"""
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        latest = next(
            (entry for sid, entry in reversed(self._compactions) if sid == session_id), None
        )
        messages = self._messages[session_id]
        if latest is None:
            return CompactionState(None, None, None, {}, list(messages))
        kept = list(messages)
        if latest.first_kept_entry_id:
            cut_index = next(
                (i for i, m in enumerate(messages) if m.id == latest.first_kept_entry_id),
                None,
            )
            if cut_index is not None:
                kept = messages[cut_index:]
        return CompactionState(
            summary=latest.summary,
            entry_id=latest.id,
            first_kept_entry_id=latest.first_kept_entry_id or None,
            details=dict(latest.details),
            messages=kept,
        )

    def append_message(self, session_id: str, message: Message) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        self._messages[session_id].append(message)

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> str:
        self._compactions.append((session_id, entry))
        return entry.id

    def append_model_change(
        self, session_id: str, *, model: str = "", effort: str = ""
    ) -> None:
        """记录配置热切换(内存态,读侧后写覆盖 create 时的 header 值)。"""
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        ref = self._sessions[session_id]
        self._sessions[session_id] = replace(
            ref, model=model or ref.model, effort=effort or ref.effort
        )

    def set_meta(self, session_id: str, key: str, value: Any) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        self._meta.setdefault(session_id, {})[key] = value

    def get_meta(self, session_id: str, key: str) -> Any | None:
        return self._meta.get(session_id, {}).get(key)

    def append_usage(
        self, session_id: str, usage: dict[str, int]
    ) -> None:
        """追加一轮用量记录(cost-transparency):内存累加,与文件后端同语义。"""
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        current = self._usage.get(session_id, UsageStats())
        self._usage[session_id] = UsageStats(
            input_tokens=current.input_tokens + int(usage.get("input_tokens", 0) or 0),
            output_tokens=current.output_tokens
            + int(usage.get("output_tokens", 0) or 0),
            reasoning_tokens=current.reasoning_tokens
            + int(usage.get("reasoning_tokens", 0) or 0),
            cached_tokens=current.cached_tokens
            + int(usage.get("cached_tokens", 0) or 0),
        )

    def load_usage(self, session_id: str) -> UsageStats:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        return self._usage.get(session_id, UsageStats())

    def fork(
        self, session_id: str, target_message_id: str, new_session_id: str
    ) -> SessionRef:
        """分叉实现(内存后端):新 dict + 保留窗口消息切片 + 压缩状态复制。"""
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        if new_session_id in self._sessions:
            raise ValueError(f"会话已存在: {new_session_id}")
        messages = self._messages[session_id]
        index = next(
            (i for i, m in enumerate(messages) if m.id == target_message_id), None
        )
        if index is None:
            raise ValueError(f"消息不存在: {target_message_id}")
        if messages[index].role != "user":
            raise ValueError(f"分叉点必须是 user 消息: {target_message_id}")
        base = self._sessions[session_id]
        ref = SessionRef(
            id=new_session_id,
            timestamp=_now(),
            cwd=base.cwd,
            parent_session=session_id,
            model=base.model,
            effort=base.effort,
        )
        self._sessions[new_session_id] = ref
        # 压缩状态复制:切点前的窗口消息已被摘要,只复制切点起、分叉点前的消息。
        latest = next(
            (e for sid, e in reversed(self._compactions) if sid == session_id), None
        )
        copied = list(messages[:index])
        if latest is not None and latest.first_kept_entry_id:
            first_kept_index = next(
                (i for i, m in enumerate(messages) if m.id == latest.first_kept_entry_id),
                None,
            )
            if first_kept_index is not None:
                copied = (
                    list(messages[first_kept_index:index])
                    if first_kept_index <= index
                    else []
                )
            self._compactions.append(
                (
                    new_session_id,
                    replace(
                        latest,
                        parent_id=copied[-1].id if copied else None,
                    ),
                )
            )
        self._messages[new_session_id] = copied
        return ref

    def _ref_with_title(self, session_id: str) -> SessionRef:
        """返回带派生标题的 SessionRef(get/list 时派生,create 时为空)。"""
        base = self._sessions[session_id]
        name = self._meta.get(session_id, {}).get("name")
        first_user = next(
            (m.content for m in self._messages[session_id] if m.role == "user"),
            "",
        )
        return SessionRef(
            id=base.id,
            timestamp=base.timestamp,
            cwd=base.cwd,
            parent_session=base.parent_session,
            model=base.model,
            effort=base.effort,
            title=_derive_title(name or "", first_user),
        )
