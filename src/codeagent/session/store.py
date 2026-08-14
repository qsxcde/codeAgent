"""session/store.py:JSONL 树形会话存储(append-only,消息唯一真相)。

格式 v1(design D5,2026-08-14,self-built-orchestration):
- 一个会话 = 一个 JSONL 文件,逐 entry 追加,永不重写历史;
- ``session`` header:version / id / parentSession / timestamp / cwd;
- ``message`` entry:id / parentId / role / content / tool_calls / tool_call_id
  (parentId 显式因果链:回放 / 回滚 / 分叉基础);
- ``compaction`` entry(预留,服务后续压缩与 undo):summary + details
  (readFiles / modifiedFiles);
- 写侧按路径锁串行化(本地锁表 ``_lock_for``),读侧按声明版本解析,
  不兼容版本明确报错。

分层约束:session 可 import core(消息/事件),不 import ai / tools / config;
存储后端经 hexagonal 缝注入(组合根装配 JsonFileStore,测试注入 MemoryStore)。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from codeagent.core.messages import Message, ToolCall

CURRENT_VERSION = 1

__all__ = ["CURRENT_VERSION", "JsonFileStore", "MemoryStore", "SessionRef", "SessionStore"]


#: 文件路径 → 互斥锁(进程内写串行化;与 tools/shared/mutation_queue 同模式,
#: 但 session 层不 import tools,锁表就地实现——分层约束)。
_path_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(path: str | Path) -> threading.Lock:
    key = str(path)
    lock = _path_locks.get(key)
    if lock is None:
        with _guard:
            lock = _path_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                _path_locks[key] = lock
    return lock


@dataclass(frozen=True)
class SessionRef:
    """会话元数据(列表 / 切换入口用)。"""

    id: str
    timestamp: str
    cwd: str
    parent_session: str | None = None


@dataclass
class CompactionEntry:
    """压缩记录(预留:格式已支持,触发策略属后续会话层 change)。"""

    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None


class SessionStore(Protocol):
    """会话存储端口(hexagonal 缝)。"""

    def create(
        self,
        session_id: str,
        *,
        parent_session: str | None = None,
        cwd: str | None = None,
    ) -> SessionRef: ...

    def get(self, session_id: str) -> SessionRef | None: ...

    def list(self) -> list[SessionRef]: ...

    def load_messages(self, session_id: str) -> list[Message]: ...

    def append_message(self, session_id: str, message: Message) -> None: ...

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> None: ...


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


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


class JsonFileStore:
    """文件后端:``~/.codeagent/sessions/<id>.jsonl``(目录可注入,测试用)。"""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def _path(self, session_id: str) -> Path:
        return self._directory / f"{session_id}.jsonl"

    def create(
        self,
        session_id: str,
        *,
        parent_session: str | None = None,
        cwd: str | None = None,
    ) -> SessionRef:
        path = self._path(session_id)
        if path.exists():
            raise ValueError(f"会话已存在: {session_id}")
        self._directory.mkdir(parents=True, exist_ok=True)
        ref = SessionRef(
            id=session_id,
            timestamp=_now(),
            cwd=cwd or str(Path.cwd()),
            parent_session=parent_session,
        )
        header = {
            "type": "session",
            "version": CURRENT_VERSION,
            "id": ref.id,
            "parentSession": ref.parent_session,
            "timestamp": ref.timestamp,
            "cwd": ref.cwd,
        }
        with _lock_for(path):
            path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
        return ref

    def get(self, session_id: str) -> SessionRef | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        for entry in self._read_entries(path):
            if entry.get("type") == "session":
                return SessionRef(
                    id=entry["id"],
                    timestamp=entry.get("timestamp", ""),
                    cwd=entry.get("cwd", ""),
                    parent_session=entry.get("parentSession"),
                )
        return None

    def list(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        if not self._directory.exists():
            return refs
        for path in sorted(self._directory.glob("*.jsonl")):
            ref = self.get(path.stem)
            if ref is not None:
                refs.append(ref)
        return refs

    def load_messages(self, session_id: str) -> list[Message]:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        messages: list[Message] = []
        for entry in self._read_entries(path):
            if entry.get("type") == "message":
                messages.append(_dict_to_message(entry))
        return messages

    def append_message(self, session_id: str, message: Message) -> None:
        self._append(session_id, _message_to_dict(message))

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> None:
        record = {
            "type": "compaction",
            "id": entry.parent_id or "",
            "parentId": entry.parent_id,
            "timestamp": _now(),
            "summary": entry.summary,
            "details": entry.details,
        }
        self._append(session_id, record)

    def _append(self, session_id: str, record: dict[str, Any]) -> None:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _lock_for(path):
            with path.open("a", encoding="utf-8") as f:
                f.write(line)

    def _read_entries(self, path: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        with _lock_for(path):
            for line_no, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"会话文件损坏 {path}:{line_no}: {exc}") from exc
                entries.append(entry)
        if not entries or entries[0].get("type") != "session":
            raise ValueError(f"会话文件缺少 header: {path}")
        version = entries[0].get("version")
        if version != CURRENT_VERSION:
            raise ValueError(
                f"会话文件版本不兼容 {path}: version={version}, 期望 {CURRENT_VERSION}"
            )
        return entries


class MemoryStore:
    """内存后端(测试 / 一次性 headless 用),零文件系统依赖。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRef] = {}
        self._messages: dict[str, list[Message]] = {}
        self._compactions: list[tuple[str, CompactionEntry]] = []

    def create(
        self,
        session_id: str,
        *,
        parent_session: str | None = None,
        cwd: str | None = None,
    ) -> SessionRef:
        if session_id in self._sessions:
            raise ValueError(f"会话已存在: {session_id}")
        ref = SessionRef(
            id=session_id,
            timestamp=_now(),
            cwd=cwd or str(Path.cwd()),
            parent_session=parent_session,
        )
        self._sessions[session_id] = ref
        self._messages[session_id] = []
        return ref

    def get(self, session_id: str) -> SessionRef | None:
        return self._sessions.get(session_id)

    def list(self) -> list[SessionRef]:
        return sorted(self._sessions.values(), key=lambda r: r.timestamp)

    def load_messages(self, session_id: str) -> list[Message]:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        return list(self._messages[session_id])

    def append_message(self, session_id: str, message: Message) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        self._messages[session_id].append(message)

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> None:
        self._compactions.append((session_id, entry))
