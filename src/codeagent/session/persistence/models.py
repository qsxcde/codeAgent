"""Session storage data models and protocol contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

from codeagent.core.contracts.messages import Message, new_id

CURRENT_VERSION = 1

__all__ = [
    "CURRENT_VERSION",
    "CompactionEntry",
    "CompactionState",
    "SessionQuery",
    "SessionRef",
    "SessionStore",
    "UsageStats",
]

SESSION_STATUSES = frozenset({"idle", "running", "completed", "failed", "cancelled"})

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

    - ``timestamp``:会话创建时间;
    - ``last_activity_at``:最近一次成功追加消息的时间;空值仅用于兼容
      外部构造的旧引用,存储后端会回退到 ``timestamp``;
    - ``model`` / ``effort``:会话创建时的模型配置(header 记录,读侧透传);
    - ``title``:派生标题(显式命名优先,否则首条用户消息截断)。
    - ``status``:运行态展示值;旧引用和持久化索引缺省为 ``idle``。
    - ``archived``:归档状态;旧引用和旧索引缺省为未归档。
    """

    id: str
    timestamp: str
    cwd: str
    parent_session: str | None = None
    model: str = ""
    effort: str = ""
    title: str = ""
    last_activity_at: str = ""
    status: str = "idle"
    archived: bool = False


@dataclass(frozen=True)
class SessionQuery:
    """会话列表查询条件(只读,不改变会话或持久化内容)。"""

    text: str = ""
    model: str = ""
    after: str = ""
    before: str = ""
    status: str = ""
    archived: bool | None = False

    def __post_init__(self) -> None:
        for field_name in ("text", "model", "after", "before", "status"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"查询字段必须是字符串: {field_name}")
            object.__setattr__(self, field_name, value.strip())
        if self.archived is not None and type(self.archived) is not bool:
            raise TypeError("archived 查询条件必须是 bool 或 None")
        if self.status and self.status.casefold() not in SESSION_STATUSES:
            allowed = ", ".join(sorted(SESSION_STATUSES))
            raise ValueError(f"未知会话状态: {self.status}; 可选值: {allowed}")
        if self.status:
            object.__setattr__(self, "status", self.status.casefold())
        for field_name in ("after", "before"):
            value = getattr(self, field_name)
            if value:
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError(f"时间格式无效: {value}") from exc
        if self.after and self.before and self.after > self.before:
            raise ValueError("时间范围无效: after 不能晚于 before")

    def matches(self, ref: SessionRef) -> bool:
        """判断一个列表引用是否满足条件。"""
        if self.text:
            haystack = f"{ref.title} {ref.id}".casefold()
            if self.text.casefold() not in haystack:
                return False
        if self.model and self.model.casefold() not in ref.model.casefold():
            return False
        activity = ref.last_activity_at or ref.timestamp
        if self.after and activity < self.after:
            return False
        if self.before and activity > self.before:
            return False
        if self.status and getattr(ref, "status", "idle") != self.status:
            return False
        if self.archived is not None and getattr(ref, "archived", False) != self.archived:
            return False
        return True

    def without_status(self) -> SessionQuery:
        """返回供持久化层使用的查询,运行态状态留给会话管理器覆盖。"""
        return replace(self, status="")


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

    def list(self, query: SessionQuery | None = None) -> list[SessionRef]: ...

    def archive(self, session_id: str, *, archived: bool = True) -> None: ...

    def delete(self, session_id: str) -> None: ...

    def load_messages(self, session_id: str) -> list[Message]: ...

    def load_context(self, session_id: str) -> CompactionState:
        """重构压缩后的上下文状态:最新摘要 + 保留消息(无压缩 = 全量)。"""

    def append_message(self, session_id: str, message: Message) -> None: ...

    def commit_turn(
        self,
        session_id: str,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        """Atomically append one successful turn and its usage metadata.

        Backends may implement this with a native transaction or a bounded
        append-and-restore operation.  The session layer never calls the
        individual append methods for a backend that provides this port.
        """

    def append_compaction(self, session_id: str, entry: CompactionEntry) -> str: ...

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
