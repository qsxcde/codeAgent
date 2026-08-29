"""Rebuildable metadata index for JSONL session files."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from codeagent.session.persistence.codec import _derive_title
from codeagent.session.persistence.index_validation import validate_index
from codeagent.session.persistence.models import SessionRef

_INDEX_VERSION = 1


class SessionIndex:
    """Keep derived metadata independent from the JSONL backend."""

    def __init__(
        self,
        directory: Path,
        entry_iter: Callable[[Path], Iterator[dict[str, Any]]],
        lock_for: Callable[[str | Path], threading.RLock],
        chmod_private: Callable[[Path], None],
        private_dir: Callable[[], None],
    ) -> None:
        self._directory = Path(directory)
        self._entry_iter = entry_iter
        self._lock_for = lock_for
        self._chmod_private = chmod_private
        self._private_dir = private_dir

    @staticmethod
    def _index_path(path: Path) -> Path:
        return path.with_suffix(".index.json")

    @staticmethod
    def _source_fingerprint(path: Path) -> dict[str, int]:
        stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}

    def new_index(
        self,
        path: Path,
        header: dict[str, Any],
        *,
        source_fingerprint: Callable[[Path], dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        fingerprint = source_fingerprint or self._source_fingerprint
        return {
            "version": _INDEX_VERSION,
            "source": fingerprint(path),
            "session": {
                "id": header.get("id", path.stem),
                "timestamp": header.get("timestamp", ""),
                "cwd": header.get("cwd", ""),
                "lastActivityAt": header.get("lastActivityAt") or header.get("timestamp", ""),
                "parentSession": header.get("parentSession"),
                "model": header.get("model", "") or "",
                "effort": header.get("effort", "") or "",
                "title": "",
            },
            "meta": {"lastName": "", "firstUserTitle": "", "firstUserSeen": False},
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "cached_tokens": 0,
            },
            "lastCompaction": None,
        }

    def build(
        self,
        path: Path,
        *,
        source_fingerprint: Callable[[Path], dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        index: dict[str, Any] | None = None
        for entry in self._entry_iter(path):
            if index is None:
                index = self.new_index(path, entry, source_fingerprint=source_fingerprint)
                continue
            self.apply_record(index, path, entry, source_fingerprint=source_fingerprint)
        if index is None:
            raise ValueError(f"会话文件缺少 header: {path}")
        index["session"]["title"] = _derive_title(
            index["meta"]["lastName"], index["meta"]["firstUserTitle"]
        )
        index["source"] = (source_fingerprint or self._source_fingerprint)(path)
        return index

    def apply_record(
        self,
        index: dict[str, Any],
        path: Path,
        record: dict[str, Any],
        *,
        source_fingerprint: Callable[[Path], dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        entry_type = record.get("type")
        if entry_type == "message":
            self._apply_message(index, record)
        elif entry_type == "meta" and record.get("key") == "name":
            if record.get("value") is not None:
                index["meta"]["lastName"] = str(record["value"])
        elif entry_type == "model_change":
            self._apply_model_change(index, record)
        elif entry_type == "usage":
            self._apply_usage(index, record)
        elif entry_type == "compaction":
            index["lastCompaction"] = {
                "id": record.get("id", "") or "",
                "parentId": record.get("parentId"),
                "firstKeptEntryId": record.get("firstKeptEntryId", "") or "",
            }
        index["session"]["title"] = _derive_title(
            index["meta"]["lastName"], index["meta"]["firstUserTitle"]
        )
        index["source"] = (source_fingerprint or self._source_fingerprint)(path)
        return index

    @staticmethod
    def _apply_message(index: dict[str, Any], record: dict[str, Any]) -> None:
        if isinstance(record.get("timestamp"), str):
            index["session"]["lastActivityAt"] = record["timestamp"]
        if record.get("role") == "user" and not index["meta"]["firstUserSeen"]:
            content = record.get("content", "") or ""
            if content:
                index["meta"]["firstUserSeen"] = True
                index["meta"]["firstUserTitle"] = _derive_title("", content)

    @staticmethod
    def _apply_model_change(index: dict[str, Any], record: dict[str, Any]) -> None:
        for key in ("model", "effort"):
            if record.get(key) is not None:
                index["session"][key] = str(record[key])

    @staticmethod
    def _apply_usage(index: dict[str, Any], record: dict[str, Any]) -> None:
        for source, target in (
            ("input", "input_tokens"),
            ("output", "output_tokens"),
            ("reasoning", "reasoning_tokens"),
            ("cached", "cached_tokens"),
        ):
            index["usage"][target] += int(record.get(source, 0) or 0)

    def read_valid(
        self,
        path: Path,
        *,
        source_fingerprint: Callable[[Path], dict[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        fingerprint = source_fingerprint or self._source_fingerprint
        try:
            data = json.loads(self._index_path(path).read_text(encoding="utf-8"))
            return validate_index(data, path, fingerprint)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_index(self, path: Path, index: dict[str, Any]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._private_dir()
        index_path = self._index_path(path)
        temp_path = index_path.with_name(
            f".{index_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temp_path.open("w", encoding="utf-8") as stream:
                json.dump(index, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._chmod_private(temp_path)
            os.replace(temp_path, index_path)
            self._chmod_private(index_path)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass

    def invalidate(self, path: Path) -> None:
        try:
            self._index_path(path).unlink()
        except OSError:
            pass

    def safe_write(self, path: Path, index: dict[str, Any]) -> None:
        try:
            self._write_index(path, index)
        except Exception:
            self.invalidate(path)

    def for_read(
        self,
        path: Path,
        *,
        source_fingerprint: Callable[[Path], dict[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock_for(path):
            index = self.read_valid(path, source_fingerprint=source_fingerprint)
            if index is not None:
                return index
            try:
                index = self.build(path, source_fingerprint=source_fingerprint)
            except Exception:
                return None
            self.safe_write(path, index)
            return index

    @staticmethod
    def ref_from_index(index: dict[str, Any], session_id: str) -> SessionRef:
        session = index["session"]
        return SessionRef(
            id=session.get("id", session_id),
            timestamp=session.get("timestamp", ""),
            cwd=session.get("cwd", ""),
            last_activity_at=session.get("lastActivityAt") or session.get("timestamp", ""),
            parent_session=session.get("parentSession"),
            model=session.get("model", "") or "",
            effort=session.get("effort", "") or "",
            title=session.get("title", "") or "",
        )
