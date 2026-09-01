"""In-memory session store used by tests and one-shot runs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from codeagent.core.contracts.messages import Message
from codeagent.session.persistence.codec import _now
from codeagent.session.persistence.memory_metadata import MemoryMetadataMixin
from codeagent.session.persistence.memory_recovery import MemoryRecoveryMixin
from codeagent.session.persistence.models import (
    CompactionEntry,
    CompactionState,
    SessionQuery,
    SessionRef,
    SubagentRunRecord,
    UsageStats,
)
from codeagent.session.persistence.subagent_records import fold_records

class MemoryStore(MemoryRecoveryMixin, MemoryMetadataMixin):
    """内存后端(测试 / 一次性 headless 用),零文件系统依赖。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRef] = {}
        self._messages: dict[str, list[Message]] = {}
        self._compactions: list[tuple[str, CompactionEntry]] = []
        self._meta: dict[str, dict[str, Any]] = {}
        self._usage: dict[str, UsageStats] = {}
        self._subagent_records: dict[str, list[SubagentRunRecord]] = {}
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
        created_at = _now()
        ref = SessionRef(
            id=session_id,
            timestamp=created_at,
            cwd=cwd or str(Path.cwd()),
            last_activity_at=created_at,
            parent_session=parent_session,
            model=model or "",
            effort=effort or "",
        )
        self._sessions[session_id] = ref
        self._messages[session_id] = []
        self._subagent_records[session_id] = []
        return ref
    def get(self, session_id: str) -> SessionRef | None:
        if session_id not in self._sessions:
            return None
        return self._ref_with_title(session_id)
    def list(self, query: SessionQuery | None = None) -> list[SessionRef]:
        refs = [self._ref_with_title(sid) for sid in self._sessions]
        refs.sort(key=lambda r: (r.last_activity_at or r.timestamp, r.id))
        effective_query = query or SessionQuery()
        return [ref for ref in refs if effective_query.matches(ref)]

    def archive(self, session_id: str, *, archived: bool = True) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        if type(archived) is not bool:
            raise TypeError("archived 必须是 bool")
        self._meta.setdefault(session_id, {})["archived"] = archived

    def delete(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        self._sessions.pop(session_id)
        self._messages.pop(session_id, None)
        self._meta.pop(session_id, None)
        self._usage.pop(session_id, None)
        self._subagent_records.pop(session_id, None)
        self._compactions = [
            (sid, entry) for sid, entry in self._compactions if sid != session_id
        ]

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
        ref = self._sessions[session_id]
        self._sessions[session_id] = replace(ref, last_activity_at=_now())

    def commit_turn(
        self,
        session_id: str,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        """Append a turn with an in-memory transaction boundary.

        The append methods remain the mutation seam so failure-injection
        stores used by contract tests exercise the same behavior as callers
        that use the public store API.  A failed append restores every field
        touched by the turn, including the deferred-session header state.
        """
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        if not messages:
            return
        original_ref = self._sessions[session_id]
        original_messages = list(self._messages[session_id])
        original_usage = self._usage.get(session_id, UsageStats())
        had_meta = session_id in self._meta
        original_meta = dict(self._meta.get(session_id, {}))
        try:
            for message in messages:
                self.append_message(session_id, message)
            if any(
                (
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.reasoning_tokens,
                    usage.cached_tokens,
                )
            ):
                self.append_usage(
                    session_id,
                    {
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "reasoning_tokens": usage.reasoning_tokens,
                        "cached_tokens": usage.cached_tokens,
                    },
                )
                if context_tokens is not None:
                    self.set_meta(session_id, "last_context_tokens", context_tokens)
        except BaseException:
            self._sessions[session_id] = original_ref
            self._messages[session_id] = original_messages
            if original_usage == UsageStats():
                self._usage.pop(session_id, None)
            else:
                self._usage[session_id] = original_usage
            if had_meta:
                self._meta[session_id] = original_meta
            else:
                self._meta.pop(session_id, None)
            raise

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> str:
        self._compactions.append((session_id, entry))
        return entry.id

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

    def append_subagent_record(self, session_id: str, record: SubagentRunRecord) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        if not isinstance(record, SubagentRunRecord):
            raise TypeError("record must be a SubagentRunRecord")
        self._subagent_records.setdefault(session_id, []).append(record)

    def load_subagent_records(self, session_id: str) -> list[SubagentRunRecord]:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        return fold_records(self._subagent_records.get(session_id, ()))

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
        created_at = _now()
        ref = SessionRef(
            id=new_session_id,
            timestamp=created_at,
            cwd=base.cwd,
            last_activity_at=created_at,
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
        self._subagent_records[new_session_id] = []
        return ref
