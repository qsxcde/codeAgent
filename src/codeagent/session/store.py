"""session/store.py:JSONL 树形会话存储(append-only,消息唯一真相)。

格式 v1(design D2~D4/D7,2026-08-14,self-built-orchestration + session-manager):
- 一个会话 = 一个 JSONL 文件,逐 entry 追加,永不重写历史;
- ``session`` header:version / id / parentSession / timestamp / cwd /
  model / effort(model/effort 为可选字段,创建时即知,旧文件缺失向后兼容);
- ``message`` entry:id / parentId / role / content / tool_calls / tool_call_id
  (parentId 显式因果链:回放 / 回滚 / 分叉基础);
- ``meta`` entry:key / value(可变元数据,如显示名;append-only 下后写覆盖,
  读侧取该键最近一次的值——对齐 Pi 的 ``session_info`` entry);
- ``compaction`` entry(预留,服务后续压缩与 undo):summary + details
  (readFiles / modifiedFiles);
- 写侧按路径锁串行化(本地锁表 ``_lock_for``),读侧按声明版本解析,
  不兼容版本明确报错。

标题派生(design D3):显式命名(meta key="name")优先,否则取首条 user
消息截断至 20 字符。扫描不能提前终止——meta 可能写在首条 user 消息之后。

分层约束:session 可 import core(消息/事件),不 import ai / tools / config;
存储后端经 hexagonal 缝注入(组合根装配 JsonFileStore,测试注入 MemoryStore)。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from codeagent.core.messages import Message, ToolCall

CURRENT_VERSION = 1

#: 派生标题截断长度(design D3)。
TITLE_MAX = 20

__all__ = [
    "CURRENT_VERSION",
    "CompactionEntry",
    "JsonFileStore",
    "MemoryStore",
    "SessionRef",
    "SessionStore",
    "TITLE_MAX",
]


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
    """会话元数据(列表 / 切换入口用)。

    - ``model`` / ``effort``:会话创建时的模型配置(header 记录,读侧透传);
    - ``title``:派生标题(显式命名优先,否则首条用户消息截断)。
    """

    id: str
    timestamp: str
    cwd: str
    parent_session: str | None = None
    model: str = ""
    effort: str = ""
    title: str = ""


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
        model: str | None = None,
        effort: str | None = None,
    ) -> SessionRef: ...

    def get(self, session_id: str) -> SessionRef | None: ...

    def list(self) -> list[SessionRef]: ...

    def load_messages(self, session_id: str) -> list[Message]: ...

    def append_message(self, session_id: str, message: Message) -> None: ...

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> None: ...

    def append_model_change(
        self, session_id: str, *, model: str = "", effort: str = ""
    ) -> None: ...

    def set_meta(self, session_id: str, key: str, value: Any) -> None: ...

    def get_meta(self, session_id: str, key: str) -> Any | None: ...


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
        model: str | None = None,
        effort: str | None = None,
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
        }
        # model/effort 可选字段:旧文件缺失时读侧 .get 默认空(向后兼容,D7)。
        if model is not None:
            header["model"] = model
        if effort is not None:
            header["effort"] = effort
        with _lock_for(path):
            path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
        return ref

    def get(self, session_id: str) -> SessionRef | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        header, first_user, last_name, model, effort = self._scan(path)
        return SessionRef(
            id=header.get("id", session_id),
            timestamp=header.get("timestamp", ""),
            cwd=header.get("cwd", ""),
            parent_session=header.get("parentSession"),
            model=model,
            effort=effort,
            title=_derive_title(last_name, first_user),
        )

    def list(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        if not self._directory.exists():
            return refs
        for path in self._directory.glob("*.jsonl"):
            ref = self.get(path.stem)
            if ref is not None:
                refs.append(ref)
        # 按时间升序(毫秒精度);同时间按 id 兜底,保证 continue_recent 确定性。
        refs.sort(key=lambda r: (r.timestamp, r.id))
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

    def append_model_change(
        self, session_id: str, *, model: str = "", effort: str = ""
    ) -> None:
        """记录配置热切换:model_change entry 追加(读侧后写覆盖 header)。"""
        record: dict[str, Any] = {"type": "model_change", "timestamp": _now()}
        if model:
            record["model"] = model
        if effort:
            record["effort"] = effort
        self._append(session_id, record)

    def set_meta(self, session_id: str, key: str, value: Any) -> None:
        """写入可变元数据:作为 meta entry 追加(后写覆盖,读侧取最新)。"""
        self._append(
            session_id,
            {"type": "meta", "key": key, "value": value, "timestamp": _now()},
        )

    def get_meta(self, session_id: str, key: str) -> Any | None:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        found: Any = None
        for entry in self._read_entries(path):
            if entry.get("type") == "meta" and entry.get("key") == key:
                found = entry.get("value")
        return found

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
        if not entries:
            raise ValueError(f"会话文件缺少 header: {path}")
        _validate_header(entries[0], path)
        return entries

    def _scan(self, path: Path) -> tuple[dict[str, Any], str, str, str, str]:
        """单遍流式扫描:header / 首条 user 消息 / 最新 meta name / 最新配置。

        不能提前终止——meta name 与 model_change 可能写在首条 user 消息之后
        (后写覆盖),提前终止会漏掉显式命名与热切换配置。内存 O(1)。
        """
        header: dict[str, Any] | None = None
        first_user = ""
        last_name = ""
        model = ""
        effort = ""
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
                if header is None:
                    _validate_header(entry, path)
                    header = entry
                    model = entry.get("model", "") or ""
                    effort = entry.get("effort", "") or ""
                elif entry.get("type") == "message" and not first_user:
                    if entry.get("role") == "user":
                        first_user = entry.get("content", "") or ""
                elif entry.get("type") == "meta" and entry.get("key") == "name":
                    if entry.get("value") is not None:
                        last_name = str(entry["value"])
                elif entry.get("type") == "model_change":
                    if entry.get("model") is not None:
                        model = str(entry["model"])
                    if entry.get("effort") is not None:
                        effort = str(entry["effort"])
        if header is None:
            raise ValueError(f"会话文件缺少 header: {path}")
        return header, first_user, last_name, model, effort


class MemoryStore:
    """内存后端(测试 / 一次性 headless 用),零文件系统依赖。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRef] = {}
        self._messages: dict[str, list[Message]] = {}
        self._compactions: list[tuple[str, CompactionEntry]] = []
        self._meta: dict[str, dict[str, Any]] = {}

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

    def append_message(self, session_id: str, message: Message) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"会话不存在: {session_id}")
        self._messages[session_id].append(message)

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> None:
        self._compactions.append((session_id, entry))

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
