"""Fork construction for the JSONL file store."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from codeagent.session.persistence.models import CURRENT_VERSION, SessionRef


class JsonlForkingMixin:
    """Copy a valid prefix into a new session without modifying the source."""

    def fork(self, session_id: str, target_message_id: str, new_session_id: str) -> SessionRef:
        path = self._path(session_id)
        new_path = self._path(new_session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        if new_path.exists():
            raise ValueError(f"会话已存在: {new_session_id}")
        header, target_found, target_is_user, latest_compaction = self._read_fork_source(
            path, target_message_id
        )
        if not target_found:
            raise ValueError(f"消息不存在: {target_message_id}")
        if not target_is_user:
            raise ValueError(f"分叉点必须是 user 消息: {target_message_id}")
        ref, new_header = self._fork_header(header, session_id, new_session_id)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._private_dir()
        temp_path = new_path.with_name(
            f".{new_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        first_kept = str((latest_compaction or {}).get("firstKeptEntryId") or "")
        try:
            cut_found, _ = self._write_fork_file(
                path,
                temp_path,
                new_header,
                target_message_id,
                first_kept,
                copy_all=latest_compaction is None or not first_kept,
                latest_compaction=latest_compaction,
            )
            if latest_compaction is not None and first_kept and not cut_found:
                self._write_fork_file(
                    path,
                    temp_path,
                    new_header,
                    target_message_id,
                    first_kept,
                    copy_all=True,
                    latest_compaction=latest_compaction,
                )
            self._chmod_private(temp_path)
            with self._lock_for(new_path):
                if new_path.exists():
                    raise ValueError(f"会话已存在: {new_session_id}")
                os.replace(temp_path, new_path)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
        self._chmod_private(new_path)
        self._safe_write_index(new_path, self._build_index(new_path))
        return ref

    def _read_fork_source(
        self,
        path: Path,
        target_message_id: str,
    ) -> tuple[dict[str, Any], bool, bool, dict[str, Any] | None]:
        header: dict[str, Any] | None = None
        target_found = False
        target_is_user = False
        latest_compaction = None
        for entry in self._iter_entries(path):
            if header is None:
                header = entry
            elif entry.get("type") == "compaction":
                latest_compaction = entry
            elif entry.get("type") == "message" and entry.get("id") == target_message_id:
                target_found = True
                target_is_user = entry.get("role") == "user"
        if header is None:
            raise ValueError(f"会话文件缺少 header: {path}")
        return header, target_found, target_is_user, latest_compaction

    def _fork_header(
        self,
        header: dict[str, Any],
        parent_session: str,
        new_session_id: str,
    ) -> tuple[SessionRef, dict[str, Any]]:
        created_at = self._now()
        ref = SessionRef(
            id=new_session_id,
            timestamp=created_at,
            cwd=header.get("cwd", "") or str(Path.cwd()),
            last_activity_at=created_at,
            parent_session=parent_session,
            model=header.get("model", "") or "",
            effort=header.get("effort", "") or "",
        )
        new_header: dict[str, Any] = {
            "type": "session",
            "version": CURRENT_VERSION,
            "id": ref.id,
            "parentSession": parent_session,
            "timestamp": ref.timestamp,
            "cwd": ref.cwd,
            "lastActivityAt": ref.last_activity_at,
        }
        for key in ("model", "effort"):
            if header.get(key):
                new_header[key] = header[key]
        return ref, new_header

    def _write_fork_file(
        self,
        source_path: Path,
        destination_path: Path,
        header: dict[str, Any],
        target_message_id: str,
        first_kept_entry_id: str,
        *,
        copy_all: bool,
        latest_compaction: dict[str, Any] | None,
    ) -> tuple[bool, str | None]:
        cut_found = False
        target_seen = False
        last_copied_id: str | None = None
        with destination_path.open("w", encoding="utf-8") as destination:
            destination.write(json.dumps(header, ensure_ascii=False) + "\n")
            for entry in self._iter_entries(source_path):
                if entry.get("type") != "message":
                    continue
                message_id = entry.get("id")
                if first_kept_entry_id and message_id == first_kept_entry_id:
                    cut_found = True
                if message_id == target_message_id and not target_seen:
                    target_seen = True
                    continue
                if target_seen:
                    continue
                if copy_all or (first_kept_entry_id and cut_found):
                    destination.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    last_copied_id = str(message_id or "")
            if latest_compaction is not None:
                record = dict(latest_compaction)
                record["parentId"] = last_copied_id
                destination.write(json.dumps(record, ensure_ascii=False) + "\n")
        return cut_found, last_copied_id


__all__ = ["JsonlForkingMixin"]
