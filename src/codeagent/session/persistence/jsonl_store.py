"""JSONL file-backed session store."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator

from codeagent.core.messages import Message
from codeagent.session.persistence.codec import (
    _derive_title,
    _dict_to_message,
    _message_to_dict,
    _now,
    _validate_header,
)
from codeagent.session.persistence.index import SessionIndex
from codeagent.session.persistence.locking import path_lock
from codeagent.session.persistence.models import (
    CURRENT_VERSION,
    CompactionEntry,
    CompactionState,
    SessionRef,
    UsageStats,
)


_lock_for = path_lock




class JsonFileStore:
    """文件后端:``~/.codeagent/sessions/<id>.jsonl``(目录可注入,测试用)。"""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._index = SessionIndex(
            self._directory,
            self._iter_entries,
            _lock_for,
            self._chmod_private,
            self._private_dir,
        )

    def _path(self, session_id: str) -> Path:
        return self._directory / f"{session_id}.jsonl"

    # Compatibility adapters for the previous JsonFileStore private surface.
    # They also keep monkeypatch-based failure tests attached to the backend.
    def _index_path(self, path: Path) -> Path:
        return self._index._index_path(path)

    def _source_fingerprint(self, path: Path) -> dict[str, int]:
        return self._index._source_fingerprint(path)

    def _new_index(self, path: Path, header: dict[str, Any]) -> dict[str, Any]:
        return self._index.new_index(
            path,
            header,
            source_fingerprint=self._source_fingerprint,
        )

    def _build_index(self, path: Path) -> dict[str, Any]:
        return self._index.build(path, source_fingerprint=self._source_fingerprint)

    def _apply_index_record(
        self, index: dict[str, Any], path: Path, record: dict[str, Any]
    ) -> dict[str, Any]:
        return self._index.apply_record(
            index,
            path,
            record,
            source_fingerprint=self._source_fingerprint,
        )

    def _read_valid_index(self, path: Path) -> dict[str, Any] | None:
        return self._index.read_valid(path, source_fingerprint=self._source_fingerprint)

    def _write_index(self, path: Path, index: dict[str, Any]) -> None:
        self._index._write_index(path, index)

    def _invalidate_index(self, path: Path) -> None:
        self._index.invalidate(path)

    def _safe_write_index(self, path: Path, index: dict[str, Any]) -> None:
        try:
            self._write_index(path, index)
        except Exception:
            self._invalidate_index(path)

    def _index_for_read(self, path: Path) -> dict[str, Any] | None:
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

    def _ref_from_index(self, index: dict[str, Any], session_id: str) -> SessionRef:
        return self._index.ref_from_index(index, session_id)

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
        header: dict[str, Any] = {
            "type": "session",
            "version": CURRENT_VERSION,
            "id": ref.id,
            "parentSession": ref.parent_session,
            "timestamp": ref.timestamp,
            "cwd": ref.cwd,
            "lastActivityAt": ref.last_activity_at,
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
        header, first_user, last_name, model, effort, last_activity_at = self._scan(path)
        return SessionRef(
            id=header.get("id", session_id),
            timestamp=header.get("timestamp", ""),
            cwd=header.get("cwd", ""),
            last_activity_at=last_activity_at
            or header.get("lastActivityAt")
            or header.get("timestamp", ""),
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
        refs.sort(key=lambda r: (r.last_activity_at or r.timestamp, r.id))
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
        record = _message_to_dict(message)
        record["timestamp"] = _now()
        self._append(session_id, record)

    def commit_turn(
        self,
        session_id: str,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        """Append one turn and usage with a recoverable file boundary.

        JSONL remains append-only for successful writes.  During a failed
        batch we truncate back to the original byte offset and restore the
        derived index, so a partial message/usage pair is never observable
        through the store API.
        """
        path = self._path(session_id)
        if not path.exists():
            raise ValueError(f"会话不存在: {session_id}")
        if not messages:
            return
        index_path = self._index_path(path)
        with _lock_for(path):
            # The snapshot, complete append batch, and rollback share one
            # lock. Otherwise a writer can append between the failed batch and
            # recovery and be erased by our failure recovery.
            original = path.read_bytes()
            original_index = index_path.read_bytes() if index_path.exists() else None
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
                path.write_bytes(original)
                self._chmod_private(path)
                if original_index is None:
                    self._invalidate_index(path)
                else:
                    index_path.write_bytes(original_index)
                    self._chmod_private(index_path)
                raise

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
        created_at = _now()
        ref = SessionRef(
            id=new_session_id,
            timestamp=created_at,
            cwd=header.get("cwd", "") or str(Path.cwd()),
            last_activity_at=created_at,
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
            "lastActivityAt": ref.last_activity_at,
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

    def _scan(
        self, path: Path
    ) -> tuple[dict[str, Any], str, str, str, str, str]:
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
        last_activity_at = ""
        for entry in self._iter_entries(path):
            if header is None:
                _validate_header(entry, path)
                header = entry
                model = entry.get("model", "") or ""
                effort = entry.get("effort", "") or ""
                last_activity_at = entry.get("lastActivityAt") or entry.get(
                    "timestamp", ""
                )
            elif entry.get("type") == "message":
                if isinstance(entry.get("timestamp"), str):
                    last_activity_at = entry["timestamp"]
                if not first_user and entry.get("role") == "user":
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
        return header, first_user, last_name, model, effort, last_activity_at
