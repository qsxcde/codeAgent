"""Rebuildable metadata index for JSONL session files."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from codeagent.session.persistence.codec import _derive_title
from codeagent.session.persistence.models import SessionRef

_INDEX_VERSION = 1


class SessionIndex:
    """Index operations kept independent from the JSONL backend implementation."""

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
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

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
                "lastActivityAt": header.get("lastActivityAt")
                or header.get("timestamp", ""),
                "parentSession": header.get("parentSession"),
                "model": header.get("model", "") or "",
                "effort": header.get("effort", "") or "",
                "title": "",
            },
            "meta": {
                "lastName": "",
                "firstUserTitle": "",
                "firstUserSeen": False,
            },
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
        """从 JSONL 单遍重建轻量索引,不保留历史 entry。"""
        index: dict[str, Any] | None = None
        for entry in self._entry_iter(path):
            if index is None:
                index = self.new_index(
                    path,
                    entry,
                    source_fingerprint=source_fingerprint,
                )
                continue
            entry_type = entry.get("type")
            if entry_type == "message":
                meta = index["meta"]
                if isinstance(entry.get("timestamp"), str):
                    index["session"]["lastActivityAt"] = entry["timestamp"]
                content = entry.get("content", "") or ""
                if entry.get("role") == "user" and not meta["firstUserSeen"] and content:
                    meta["firstUserSeen"] = True
                    meta["firstUserTitle"] = _derive_title("", content)
            elif entry_type == "meta" and entry.get("key") == "name":
                if entry.get("value") is not None:
                    index["meta"]["lastName"] = str(entry["value"])
            elif entry_type == "model_change":
                session = index["session"]
                if entry.get("model") is not None:
                    session["model"] = str(entry["model"])
                if entry.get("effort") is not None:
                    session["effort"] = str(entry["effort"])
            elif entry_type == "usage":
                usage = index["usage"]
                usage["input_tokens"] += int(entry.get("input", 0) or 0)
                usage["output_tokens"] += int(entry.get("output", 0) or 0)
                usage["reasoning_tokens"] += int(entry.get("reasoning", 0) or 0)
                usage["cached_tokens"] += int(entry.get("cached", 0) or 0)
            elif entry_type == "compaction":
                index["lastCompaction"] = {
                    "id": entry.get("id", "") or "",
                    "parentId": entry.get("parentId"),
                    "firstKeptEntryId": entry.get("firstKeptEntryId", "") or "",
                }
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
        """在已验证的索引上应用一次追加,避免每次写入重扫历史。"""
        entry_type = record.get("type")
        if entry_type == "message":
            meta = index["meta"]
            if isinstance(record.get("timestamp"), str):
                index["session"]["lastActivityAt"] = record["timestamp"]
            content = record.get("content", "") or ""
            if record.get("role") == "user" and not meta["firstUserSeen"] and content:
                meta["firstUserSeen"] = True
                meta["firstUserTitle"] = _derive_title("", content)
        elif entry_type == "meta" and record.get("key") == "name":
            if record.get("value") is not None:
                index["meta"]["lastName"] = str(record["value"])
        elif entry_type == "model_change":
            session = index["session"]
            if record.get("model") is not None:
                session["model"] = str(record["model"])
            if record.get("effort") is not None:
                session["effort"] = str(record["effort"])
        elif entry_type == "usage":
            usage = index["usage"]
            usage["input_tokens"] += int(record.get("input", 0) or 0)
            usage["output_tokens"] += int(record.get("output", 0) or 0)
            usage["reasoning_tokens"] += int(record.get("reasoning", 0) or 0)
            usage["cached_tokens"] += int(record.get("cached", 0) or 0)
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

    def read_valid(
        self,
        path: Path,
        *,
        source_fingerprint: Callable[[Path], dict[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        fingerprint = source_fingerprint or self._source_fingerprint
        index_path = self._index_path(path)
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            if type(data.get("version")) is not int or data["version"] != _INDEX_VERSION:
                return None
            source = data.get("source")
            if not isinstance(source, dict):
                return None
            if not all(
                isinstance(source.get(key), int) and not isinstance(source.get(key), bool)
                for key in ("size", "mtime_ns")
            ):
                return None
            if source != fingerprint(path):
                return None
            session = data.get("session")
            if not isinstance(session, dict):
                return None
            if not all(
                key in session and isinstance(session[key], str)
                for key in (
                    "id",
                    "timestamp",
                    "cwd",
                    "lastActivityAt",
                    "model",
                    "effort",
                    "title",
                )
            ):
                return None
            if "parentSession" not in session or not isinstance(
                session["parentSession"], (str, type(None))
            ):
                return None
            meta = data.get("meta")
            if not isinstance(meta, dict):
                return None
            if not all(
                key in meta
                for key in ("lastName", "firstUserTitle", "firstUserSeen")
            ):
                return None
            if not isinstance(meta["lastName"], str):
                return None
            if not isinstance(meta["firstUserTitle"], str):
                return None
            if not isinstance(meta["firstUserSeen"], bool):
                return None
            usage = data.get("usage")
            if not isinstance(usage, dict):
                return None
            if not all(
                key in usage
                and isinstance(usage[key], int)
                and not isinstance(usage[key], bool)
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                    "cached_tokens",
                )
            ):
                return None
            if "lastCompaction" not in data:
                return None
            compaction = data["lastCompaction"]
            if compaction is not None and not isinstance(compaction, dict):
                return None
            if compaction is not None:
                if not all(
                    key in compaction
                    for key in ("id", "parentId", "firstKeptEntryId")
                ):
                    return None
                if not isinstance(compaction["id"], str):
                    return None
                if not isinstance(compaction["firstKeptEntryId"], str):
                    return None
                if not isinstance(compaction["parentId"], (str, type(None))):
                    return None
            return data
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_index(self, path: Path, index: dict[str, Any]) -> None:
        """以同目录临时文件原子替换索引,索引权限与会话文件一致。"""
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
        """缓存失败不得阻塞 JSONL 真相源的写入或读取。"""
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
        """优先命中索引,否则流式重建;失败时返回 None 让调用方直读。"""
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
    def ref_from_index(
        index: dict[str, Any], session_id: str
    ) -> SessionRef:
        session = index["session"]
        return SessionRef(
            id=session.get("id", session_id),
            timestamp=session.get("timestamp", ""),
            cwd=session.get("cwd", ""),
            last_activity_at=session.get("lastActivityAt")
            or session.get("timestamp", ""),
            parent_session=session.get("parentSession"),
            model=session.get("model", "") or "",
            effort=session.get("effort", "") or "",
            title=session.get("title", "") or "",
        )
