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
import os
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterator, Protocol

from codeagent.core.messages import Message, ToolCall, new_id

CURRENT_VERSION = 1
_INDEX_VERSION = 1

#: 派生标题截断长度(design D3)。
TITLE_MAX = 20

__all__ = [
    "CURRENT_VERSION",
    "CompactionEntry",
    "CompactionState",
    "JsonFileStore",
    "MemoryStore",
    "SessionRef",
    "SessionStore",
    "TITLE_MAX",
    "UsageStats",
]


#: 文件路径 → 互斥锁(进程内写串行化;与 tools/shared/mutation_queue 同模式,
#: 但 session 层不 import tools,锁表就地实现——分层约束)。
_path_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def _lock_for(path: str | Path) -> threading.RLock:
    key = str(path)
    lock = _path_locks.get(key)
    if lock is None:
        with _guard:
            lock = _path_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                _path_locks[key] = lock
    return lock


@dataclass(frozen=True)
class UsageStats:
    """会话级用量聚合(读侧累计;cost-transparency)。

    字段与 usage 归一形状对齐(input/output/reasoning/cached);
    reasoning 保留原始计数,展示层并入 output。
    """

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0


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
    """压缩记录(对齐 Pi CompactionEntry;session-compaction 语义落地)。

    - ``id``:uuid7,构造时自动分配(供 parentId 链接回);
    - ``parent_id``:追加时的叶子(当前历史最后一条消息 / 上一次压缩记录);
    - ``first_kept_entry_id``:切点消息 id(上下文重构起点);
    - ``details``:文件操作跟踪 ``{readFiles, modifiedFiles}``(预留字段落地)。
    """

    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    first_kept_entry_id: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id()


@dataclass(frozen=True)
class CompactionState:
    """压缩后的上下文状态(读侧重构;无压缩记录时 summary/entry_id 为 None)。

    - ``summary`` / ``entry_id`` / ``details``:最新压缩记录的内容;
    - ``messages``:从 ``first_kept_entry_id`` 起的保留消息
      (被压缩窗口消息物理保留,但不出现在模型上下文)。
    """

    summary: str | None
    entry_id: str | None
    first_kept_entry_id: str | None
    details: dict[str, Any]
    messages: list[Message]


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

    def load_context(self, session_id: str) -> CompactionState:
        """重构压缩后的上下文状态:最新摘要 + 保留消息(无压缩 = 全量)。"""

    def append_message(self, session_id: str, message: Message) -> None: ...

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> None: ...

    def append_model_change(
        self, session_id: str, *, model: str = "", effort: str = ""
    ) -> None: ...

    def set_meta(self, session_id: str, key: str, value: Any) -> None: ...

    def get_meta(self, session_id: str, key: str) -> Any | None: ...

    def append_usage(
        self, session_id: str, usage: dict[str, int]
    ) -> None:
        """追加一轮用量记录(append-only usage entry;cost-transparency)。

        ``usage`` 为归一形状 ``{input_tokens, output_tokens, reasoning_tokens,
        cached_tokens}``;逐次追加,读侧 ``load_usage`` 累加聚合。
        """

    def load_usage(self, session_id: str) -> UsageStats:
        """返回会话累计用量(所有 usage entry 之和;无记录返回全零)。"""

    def fork(
        self, session_id: str, target_message_id: str, new_session_id: str
    ) -> SessionRef:
        """从既有会话分叉新会话(session-fork,对齐 Pi createBranchedSession)。

        - 分叉点 = target user 消息**之前**(复制到它之前,不含该消息);
        - 新会话 header 记录 parentSession = 原会话 id,元数据从原 header 复制;
        - 原会话文件零修改(append-only 承诺不破);分叉点非法抛 ValueError。
        """


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

    @staticmethod
    def _index_path(path: Path) -> Path:
        return path.with_suffix(".index.json")

    @staticmethod
    def _source_fingerprint(path: Path) -> dict[str, int]:
        stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

    def _new_index(self, path: Path, header: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": _INDEX_VERSION,
            "source": self._source_fingerprint(path),
            "session": {
                "id": header.get("id", path.stem),
                "timestamp": header.get("timestamp", ""),
                "cwd": header.get("cwd", ""),
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

    def _build_index(self, path: Path) -> dict[str, Any]:
        """从 JSONL 单遍重建轻量索引,不保留历史 entry。"""
        index: dict[str, Any] | None = None
        for entry in self._iter_entries(path):
            if index is None:
                index = self._new_index(path, entry)
                continue
            entry_type = entry.get("type")
            if entry_type == "message":
                meta = index["meta"]
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
        index["source"] = self._source_fingerprint(path)
        return index

    def _apply_index_record(
        self, index: dict[str, Any], path: Path, record: dict[str, Any]
    ) -> dict[str, Any]:
        """在已验证的索引上应用一次追加,避免每次写入重扫历史。"""
        entry_type = record.get("type")
        if entry_type == "message":
            meta = index["meta"]
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
        index["source"] = self._source_fingerprint(path)
        return index

    def _read_valid_index(self, path: Path) -> dict[str, Any] | None:
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
            if source != self._source_fingerprint(path):
                return None
            session = data.get("session")
            if not isinstance(session, dict):
                return None
            if not all(
                key in session and isinstance(session[key], str)
                for key in ("id", "timestamp", "cwd", "model", "effort", "title")
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

    def _invalidate_index(self, path: Path) -> None:
        try:
            self._index_path(path).unlink()
        except OSError:
            pass

    def _safe_write_index(self, path: Path, index: dict[str, Any]) -> None:
        """缓存失败不得阻塞 JSONL 真相源的写入或读取。"""
        try:
            self._write_index(path, index)
        except Exception:
            self._invalidate_index(path)

    def _index_for_read(self, path: Path) -> dict[str, Any] | None:
        """优先命中索引,否则流式重建;失败时返回 None 让调用方直读。"""
        with _lock_for(path):
            index = self._read_valid_index(path)
            if index is not None:
                return index
            try:
                index = self._build_index(path)
            except Exception:
                return None
            self._safe_write_index(path, index)
            return index

    @staticmethod
    def _ref_from_index(
        index: dict[str, Any], session_id: str
    ) -> SessionRef:
        session = index["session"]
        return SessionRef(
            id=session.get("id", session_id),
            timestamp=session.get("timestamp", ""),
            cwd=session.get("cwd", ""),
            parent_session=session.get("parentSession"),
            model=session.get("model", "") or "",
            effort=session.get("effort", "") or "",
            title=session.get("title", "") or "",
        )

    def _iter_entries(self, path: Path) -> Iterator[dict[str, Any]]:
        """逐行解析 entry:JSON 损坏行跳过(append-only 崩溃可能留残缺行,
        审计 M-4);首个有效 entry 负责 header/version 校验。"""
        header_seen = False
        with _lock_for(path):
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 残缺行容错:跳过,不阻断整文件解析
                    if not header_seen:
                        _validate_header(entry, path)
                        header_seen = True
                    yield entry
        if not header_seen:
            raise ValueError(f"会话文件缺少 header: {path}")

    @staticmethod
    def _chmod_private(path: Path) -> None:
        """会话文件收敛为 0600:转录含工具输出/文件内容/可能密钥,默认
        umask 022 下会产出 0644 世界可读(审计 M-10)。失败(只读文件系统等)
        不阻塞写入。"""
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _private_dir(self) -> None:
        """sessions 目录收敛为 0700(同级理由,审计 M-10)。"""
        try:
            os.chmod(self._directory, 0o700)
        except OSError:
            pass

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
        self._private_dir()  # sessions 目录 0700(转录含敏感内容,审计 M-10)
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
            self._chmod_private(path)  # 会话文件 0600(审计 M-10)
            try:
                self._safe_write_index(path, self._new_index(path, header))
            except Exception:
                self._invalidate_index(path)
        return ref

    def get(self, session_id: str) -> SessionRef | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        index = self._index_for_read(path)
        if index is not None:
            return self._ref_from_index(index, session_id)
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
            try:
                ref = self.get(path.stem)
            except ValueError:
                continue  # 损坏/版本不兼容会话隔离,不阻断其余枚举(审计 M-4)
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
        for entry in self._iter_entries(path):
            if entry.get("type") == "message":
                messages.append(_dict_to_message(entry))
        return messages

    def load_context(self, session_id: str) -> CompactionState:
        """重构压缩后的上下文:取最新压缩记录的摘要 + 切点起的消息。

        切点按 **精确 id 定位**(uuid7 同毫秒内不保证严格递增,不能用
        字典序比较;回归:同毫秒创建的多条消息被误过滤)。无压缩记录时
        返回全量;切点缺失(异常文件)回退全量,不丢上下文。
        """
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        latest: dict[str, Any] | None = None
        for entry in self._iter_entries(path):
            if entry.get("type") == "compaction":
                latest = entry
        if latest is None:
            return CompactionState(
                None, None, None, {}, self.load_messages(session_id)
            )
        cut = str(latest.get("firstKeptEntryId") or "")
        if cut:
            kept, cut_found = self._load_messages_from_cut(path, cut)
            if not cut_found:
                # 异常文件回退全量,与原实现保持一致,不丢上下文。
                kept = self.load_messages(session_id)
        else:
            kept = self.load_messages(session_id)
        return CompactionState(
            summary=str(latest.get("summary") or ""),
            entry_id=str(latest.get("id") or ""),
            first_kept_entry_id=cut or None,
            details=dict(latest.get("details") or {}),
            messages=kept,
        )

    def append_message(self, session_id: str, message: Message) -> None:
        self._append(session_id, _message_to_dict(message))

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> str:
        """追加压缩记录(session-compaction):entry 生成 id / parentId /
        firstKeptEntryId 语义落地,返回 entry id(供新消息 parent 链接回)。"""
        record = {
            "type": "compaction",
            "id": entry.id,
            "parentId": entry.parent_id,
            "firstKeptEntryId": entry.first_kept_entry_id,
            "timestamp": _now(),
            "summary": entry.summary,
            "details": entry.details,
        }
        self._append(session_id, record)
        return entry.id

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
        for entry in self._iter_entries(path):
            if entry.get("type") == "meta" and entry.get("key") == key:
                found = entry.get("value")
        return found

    def append_usage(
        self, session_id: str, usage: dict[str, int]
    ) -> None:
        """追加一轮用量记录(cost-transparency):usage entry 追加,不重写历史。

        ``usage`` 为归一形状 ``{input_tokens, output_tokens, reasoning_tokens,
        cached_tokens}``;缺失字段容错(缺省 0)。
        """
        record: dict[str, Any] = {
            "type": "usage",
            "timestamp": _now(),
            "input": int(usage.get("input_tokens", 0) or 0),
            "output": int(usage.get("output_tokens", 0) or 0),
            "reasoning": int(usage.get("reasoning_tokens", 0) or 0),
            "cached": int(usage.get("cached_tokens", 0) or 0),
        }
        self._append(session_id, record)

    def load_usage(self, session_id: str) -> UsageStats:
        """读侧聚合:单遍累加所有 usage entry;无记录/旧文件返回全零。"""
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        index = self._index_for_read(path)
        if index is not None:
            try:
                usage = index["usage"]
                return UsageStats(
                    input_tokens=int(usage.get("input_tokens", 0) or 0),
                    output_tokens=int(usage.get("output_tokens", 0) or 0),
                    reasoning_tokens=int(usage.get("reasoning_tokens", 0) or 0),
                    cached_tokens=int(usage.get("cached_tokens", 0) or 0),
                )
            except (AttributeError, TypeError, ValueError):
                pass
        total = UsageStats()
        for entry in self._iter_entries(path):
            if entry.get("type") != "usage":
                continue
            total = UsageStats(
                input_tokens=total.input_tokens + int(entry.get("input", 0) or 0),
                output_tokens=total.output_tokens + int(entry.get("output", 0) or 0),
                reasoning_tokens=total.reasoning_tokens
                + int(entry.get("reasoning", 0) or 0),
                cached_tokens=total.cached_tokens + int(entry.get("cached", 0) or 0),
            )
        return total

    def fork(
        self, session_id: str, target_message_id: str, new_session_id: str
    ) -> SessionRef:
        """分叉实现(文件后端):新文件 = 新 header + 保留窗口消息 + 压缩状态。

        - 消息 id / parentId 链保持(回放语义、后续引用不受影响);
        - 父会话存在压缩记录时,新会话**携带最新摘要**(压缩状态复制):
          分叉点之前、切点(firstKeptEntryId)之后的消息复制;切点之前的
          窗口消息已被摘要,不复制(否则摘要与物理消息重复);
        - 写侧走新文件路径锁(防并发创建同一新会话);原文件只读。
        """
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        new_path = self._path(new_session_id)
        if new_path.exists():
            raise ValueError(f"会话已存在: {new_session_id}")
        header: dict[str, Any] | None = None
        target_found = False
        target_is_user = False
        latest_compaction: dict[str, Any] | None = None
        for entry in self._iter_entries(path):
            if header is None:
                header = entry
                continue
            if entry.get("type") == "compaction":
                latest_compaction = entry
            elif (
                entry.get("type") == "message"
                and not target_found
                and entry.get("id") == target_message_id
            ):
                target_found = True
                target_is_user = entry.get("role") == "user"
        if not target_found:
            raise ValueError(f"消息不存在: {target_message_id}")
        if not target_is_user:
            raise ValueError(f"分叉点必须是 user 消息: {target_message_id}")
        assert header is not None
        self._directory.mkdir(parents=True, exist_ok=True)
        self._private_dir()
        ref = SessionRef(
            id=new_session_id,
            timestamp=_now(),
            cwd=header.get("cwd", "") or str(Path.cwd()),
            parent_session=session_id,
            model=header.get("model", "") or "",
            effort=header.get("effort", "") or "",
        )
        new_header: dict[str, Any] = {
            "type": "session",
            "version": CURRENT_VERSION,
            "id": ref.id,
            "parentSession": session_id,
            "timestamp": ref.timestamp,
            "cwd": ref.cwd,
        }
        if header.get("model"):
            new_header["model"] = header["model"]
        if header.get("effort"):
            new_header["effort"] = header["effort"]
        temp_path = new_path.with_name(
            f".{new_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        first_kept = str(
            (latest_compaction or {}).get("firstKeptEntryId") or ""
        )
        copy_all = latest_compaction is None or not first_kept
        try:
            cut_found, _ = self._write_fork_file(
                path,
                temp_path,
                new_header,
                target_message_id,
                first_kept,
                copy_all=copy_all,
                latest_compaction=latest_compaction,
            )
            if latest_compaction is not None and first_kept and not cut_found:
                # 损坏文件中切点缺失时,保留旧实现的全量回退语义。
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
            with _lock_for(new_path):
                if new_path.exists():
                    raise ValueError(f"会话已存在: {new_session_id}")
                os.replace(temp_path, new_path)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
        self._chmod_private(new_path)  # 分叉新文件同样 0600(审计 M-10)
        try:
            self._safe_write_index(new_path, self._build_index(new_path))
        except Exception:
            self._invalidate_index(new_path)
        return ref

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
        """流式写入分叉文件,返回切点是否在源文件中及最后复制消息 id。"""
        cut_found = False
        target_seen = False
        last_copied_id: str | None = None
        with destination_path.open("w", encoding="utf-8") as destination:
            destination.write(json.dumps(header, ensure_ascii=False) + "\n")

            for entry in self._iter_entries(source_path):
                if entry.get("type") == "message":
                    message_id = entry.get("id")
                    if first_kept_entry_id and message_id == first_kept_entry_id:
                        cut_found = True
                    if message_id == target_message_id and not target_seen:
                        target_seen = True
                        continue
                    if target_seen:
                        continue
                    if copy_all or (first_kept_entry_id and cut_found):
                        destination.write(
                            json.dumps(entry, ensure_ascii=False) + "\n"
                        )
                        last_copied_id = str(message_id or "")

            if latest_compaction is not None:
                # 压缩状态复制:摘要随新会话;parentId 接回复制窗口末尾。
                record = dict(latest_compaction)
                record["parentId"] = last_copied_id
                destination.write(json.dumps(record, ensure_ascii=False) + "\n")
        return cut_found, last_copied_id


    def _append(self, session_id: str, record: dict[str, Any]) -> None:
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _lock_for(path):
            index = self._read_valid_index(path)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            self._chmod_private(path)  # 追加后保持 0600(审计 M-10)
            try:
                if index is None:
                    index = self._build_index(path)
                else:
                    index = self._apply_index_record(index, path, record)
                self._safe_write_index(path, index)
            except Exception:
                self._invalidate_index(path)

    def _load_messages_from_cut(
        self, path: Path, first_kept_entry_id: str
    ) -> tuple[list[Message], bool]:
        """流式加载压缩切点后的消息,不构造切点之前的历史列表。"""
        messages: list[Message] = []
        cut_found = False
        for entry in self._iter_entries(path):
            if entry.get("type") != "message":
                continue
            if not cut_found and entry.get("id") == first_kept_entry_id:
                cut_found = True
            if cut_found:
                messages.append(_dict_to_message(entry))
        return messages, cut_found

    def _scan(self, path: Path) -> tuple[dict[str, Any], str, str, str, str]:
        """单遍流式扫描:header / 首条 user 消息 / 最新 meta name / 最新配置。

        不能提前终止——meta name 与 model_change 可能写在首条 user 消息之后
        (后写覆盖),提前终止会漏掉显式命名与热切换配置。内存 O(1)。
        损坏行跳过(与 _read_entries 同容错,审计 M-4)。
        """
        header: dict[str, Any] | None = None
        first_user = ""
        last_name = ""
        model = ""
        effort = ""
        for entry in self._iter_entries(path):
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
