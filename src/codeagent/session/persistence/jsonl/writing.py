"""Write-side operations for the JSONL file store."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from codeagent.core.contracts.messages import Message
from codeagent.session.persistence.codec import _message_to_dict
from codeagent.session.persistence.models import (
    CURRENT_VERSION,
    CompactionEntry,
    SessionRef,
    UsageStats,
)


class JsonlWritingMixin:
    """Append records while preserving file and index consistency."""

    def create(
        self,
        session_id: str,
        *,
        parent_session: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> SessionRef:
        path = self._path(session_id)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._private_dir()
        created_at = self._now()
        ref = SessionRef(
            id=session_id,
            timestamp=created_at,
            cwd=cwd or str(Path.cwd()),
            last_activity_at=created_at,
            parent_session=parent_session,
            model=model or "",
            effort=effort or "",
        )
        header: dict[str, Any] = {
            "type": "session",
            "version": CURRENT_VERSION,
            "id": ref.id,
            "parentSession": ref.parent_session,
            "timestamp": ref.timestamp,
            "cwd": ref.cwd,
            "lastActivityAt": ref.last_activity_at,
        }
        if model is not None:
            header["model"] = model
        if effort is not None:
            header["effort"] = effort
        with self._lock_for(path):
            if path.exists():
                raise ValueError(f"会话已存在: {session_id}")
            with path.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps(header, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._chmod_private(path)
            try:
                self._safe_write_index(path, self._new_index(path, header))
            except Exception:
                self._invalidate_index(path)
        return ref

    def append_message(self, session_id: str, message: Message) -> None:
        record = _message_to_dict(message)
        record["timestamp"] = self._now()
        self._append(session_id, record)

    def commit_turn(
        self,
        session_id: str,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        if not messages:
            return
        index_path = self._index_path(path)
        with self._lock_for(path):
            original_size = path.stat().st_size
            original_index = index_path.read_bytes() if index_path.exists() else None
            try:
                for message in messages:
                    self.append_message(session_id, message)
                if _has_usage(usage):
                    self.append_usage(session_id, _usage_record(usage))
                    if context_tokens is not None:
                        self.set_meta(session_id, "last_context_tokens", context_tokens)
            except BaseException:
                self._restore_append(path, index_path, original_size, original_index)
                raise

    def _restore_append(
        self,
        path: Path,
        index_path: Path,
        original_size: int,
        original_index: bytes | None,
    ) -> None:
        with path.open("r+b") as stream:
            stream.truncate(original_size)
            stream.flush()
            os.fsync(stream.fileno())
        self._chmod_private(path)
        if original_index is None:
            self._invalidate_index(path)
            return
        with index_path.open("wb") as stream:
            stream.write(original_index)
            stream.flush()
            os.fsync(stream.fileno())
        self._chmod_private(index_path)

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> str:
        self._append(
            session_id,
            {
                "type": "compaction",
                "id": entry.id,
                "parentId": entry.parent_id,
                "firstKeptEntryId": entry.first_kept_entry_id,
                "timestamp": self._now(),
                "summary": entry.summary,
                "details": entry.details,
            },
        )
        return entry.id

    def append_model_change(
        self,
        session_id: str,
        *,
        model: str = "",
        effort: str = "",
    ) -> None:
        record: dict[str, Any] = {"type": "model_change", "timestamp": self._now()}
        if model:
            record["model"] = model
        if effort:
            record["effort"] = effort
        self._append(session_id, record)

    def set_meta(self, session_id: str, key: str, value: Any) -> None:
        self._append(
            session_id,
            {"type": "meta", "key": key, "value": value, "timestamp": self._now()},
        )

    def archive(self, session_id: str, *, archived: bool = True) -> None:
        if type(archived) is not bool:
            raise TypeError("archived 必须是 bool")
        self._validated_session_path(session_id)
        self.set_meta(session_id, "archived", archived)

    def delete(self, session_id: str) -> None:
        """Delete one validated session file and its derived index."""
        path = self._validated_session_path(session_id)
        index_path = self._index_path(path)
        with self._lock_for(path):
            if index_path.is_symlink():
                raise ValueError(f"拒绝删除符号链接索引: {session_id}")
            if index_path.exists():
                index_path.unlink()
            try:
                path.unlink()
            except OSError:
                # The source JSONL remains the authority; a future read can
                # rebuild the missing derived index after a failed deletion.
                raise

    def _validated_session_path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("会话 id 不能为空")
        if session_id in {".", ".."} or "/" in session_id or "\\" in session_id:
            raise ValueError(f"非法会话 id: {session_id}")
        path = self._path(session_id)
        if path.parent != self._directory:
            raise ValueError(f"会话 id 越界: {session_id}")
        if path.is_symlink():
            raise ValueError(f"拒绝删除符号链接会话: {session_id}")
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        return path

    def get_meta(self, session_id: str, key: str) -> Any | None:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        found = None
        for entry in self._iter_entries(path):
            if entry.get("type") == "meta" and entry.get("key") == key:
                found = entry.get("value")
        return found

    def append_usage(self, session_id: str, usage: dict[str, int]) -> None:
        self._append(
            session_id,
            {
                "type": "usage",
                "timestamp": self._now(),
                "input": int(usage.get("input_tokens", 0) or 0),
                "output": int(usage.get("output_tokens", 0) or 0),
                "reasoning": int(usage.get("reasoning_tokens", 0) or 0),
                "cached": int(usage.get("cached_tokens", 0) or 0),
            },
        )

    def load_usage(self, session_id: str) -> UsageStats:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        index = self._index_for_read(path)
        if index is not None:
            try:
                usage = index["usage"]
                return UsageStats(**{key: int(usage.get(key, 0) or 0) for key in UsageStats.__dataclass_fields__})
            except (AttributeError, TypeError, ValueError):
                pass
        return _sum_usage(self._iter_entries(path))

    def _append(self, session_id: str, record: dict[str, Any]) -> None:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        with self._lock_for(path):
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._chmod_private(path)
            index = self._read_valid_index(path)
            if index is None:
                index = self._build_index(path)
            else:
                index = self._apply_index_record(index, path, record)
            self._safe_write_index(path, index)


def _has_usage(usage: UsageStats) -> bool:
    return any(getattr(usage, field) for field in UsageStats.__dataclass_fields__)


def _usage_record(usage: UsageStats) -> dict[str, int]:
    return {field: int(getattr(usage, field)) for field in UsageStats.__dataclass_fields__}


def _sum_usage(entries) -> UsageStats:
    total = UsageStats()
    for entry in entries:
        if entry.get("type") != "usage":
            continue
        total = UsageStats(
            input_tokens=total.input_tokens + int(entry.get("input", 0) or 0),
            output_tokens=total.output_tokens + int(entry.get("output", 0) or 0),
            reasoning_tokens=total.reasoning_tokens + int(entry.get("reasoning", 0) or 0),
            cached_tokens=total.cached_tokens + int(entry.get("cached", 0) or 0),
        )
    return total


__all__ = ["JsonlWritingMixin"]
