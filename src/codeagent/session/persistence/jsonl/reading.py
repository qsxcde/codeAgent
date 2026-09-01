"""Read-side operations for the JSONL file store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from codeagent.core.contracts.messages import Message
from codeagent.session.persistence.codec import _dict_to_message, _validate_header
from codeagent.session.persistence.models import CompactionState, SessionRef
from codeagent.session.persistence.subagent_records import (
    SubagentRunRecord,
    fold_records,
    record_from_entry,
)


class JsonlReadingMixin:
    """Stream messages and derived state from a JSONL session file."""

    def _iter_entries(self, path: Path) -> Iterator[dict[str, Any]]:
        header_seen = False
        with self._lock_for(path):
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if not header_seen:
                        _validate_header(entry, path)
                        header_seen = True
                    yield entry
        if not header_seen:
            raise ValueError(f"会话文件缺少 header: {path}")

    def load_messages(self, session_id: str) -> list[Message]:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        messages: list[Message] = []
        for entry in self._iter_entries(path):
            if entry.get("type") != "message":
                continue
            try:
                messages.append(_dict_to_message(entry))
            except (KeyError, TypeError, ValueError):
                continue
        return messages

    def load_subagent_records(self, session_id: str) -> list[SubagentRunRecord]:
        """Load and fold valid parent-owned records, ignoring local corruption."""
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        records: list[SubagentRunRecord] = []
        for entry in self._iter_entries(path):
            if entry.get("type") != "subagent":
                continue
            try:
                records.append(record_from_entry(entry))
            except (KeyError, TypeError, ValueError):
                continue
        return fold_records(records)

    def load_context(self, session_id: str) -> CompactionState:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        latest = self._latest_compaction(path)
        if latest is None:
            return CompactionState(None, None, None, {}, self.load_messages(session_id))
        cut = str(latest.get("firstKeptEntryId") or "")
        kept = self.load_messages(session_id) if not cut else self._load_messages_from_cut(path, cut)
        if cut and isinstance(kept, tuple):
            messages, found = kept
            kept = messages if found else self.load_messages(session_id)
        return CompactionState(
            summary=str(latest.get("summary") or ""),
            entry_id=str(latest.get("id") or ""),
            first_kept_entry_id=cut or None,
            details=dict(latest.get("details") or {}),
            messages=kept,
        )

    def _latest_compaction(self, path: Path) -> dict[str, Any] | None:
        latest = None
        for entry in self._iter_entries(path):
            if entry.get("type") == "compaction" and _valid_compaction(entry):
                latest = entry
        return latest

    def _load_messages_from_cut(
        self,
        path: Path,
        first_kept_entry_id: str,
    ) -> tuple[list[Message], bool]:
        messages: list[Message] = []
        cut_found = False
        for entry in self._iter_entries(path):
            if entry.get("type") != "message":
                continue
            if not cut_found and entry.get("id") == first_kept_entry_id:
                cut_found = True
            if cut_found:
                try:
                    messages.append(_dict_to_message(entry))
                except (KeyError, TypeError, ValueError):
                    continue
        return messages, cut_found

    def _scan(self, path: Path) -> tuple[dict[str, Any], str, str, str, str, str, bool]:
        header: dict[str, Any] | None = None
        first_user = ""
        last_name = ""
        model = ""
        effort = ""
        last_activity_at = ""
        archived = False
        for entry in self._iter_entries(path):
            if header is None:
                header = entry
                model = entry.get("model", "") or ""
                effort = entry.get("effort", "") or ""
                last_activity_at = entry.get("lastActivityAt") or entry.get("timestamp", "")
            elif entry.get("type") == "message":
                if isinstance(entry.get("timestamp"), str):
                    last_activity_at = entry["timestamp"]
                if not first_user and entry.get("role") == "user":
                    first_user = entry.get("content", "") or ""
            elif entry.get("type") == "meta" and entry.get("key") == "name":
                if entry.get("value") is not None:
                    last_name = str(entry["value"])
            elif entry.get("type") == "meta" and entry.get("key") == "archived":
                if type(entry.get("value")) is bool:
                    archived = entry["value"]
            elif entry.get("type") == "model_change":
                model = str(entry["model"]) if entry.get("model") is not None else model
                effort = str(entry["effort"]) if entry.get("effort") is not None else effort
        if header is None:
            raise ValueError(f"会话文件缺少 header: {path}")
        return header, first_user, last_name, model, effort, last_activity_at, archived


__all__ = ["JsonlReadingMixin"]


def _valid_compaction(entry: dict[str, Any]) -> bool:
    return (
        isinstance(entry.get("id"), str)
        and isinstance(entry.get("firstKeptEntryId"), str)
        and isinstance(entry.get("summary"), str)
        and isinstance(entry.get("details"), dict)
    )
