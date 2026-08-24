"""TUI 运行阶段快照与事件归约。

该模块只依赖标准库和 ``core.events``。它把结构化生命周期事件归约成一份
不可变快照，供状态栏、``/status`` 和离线测试共享；事件中带有显式的
``session_id``/``run_id`` 时，旧会话或旧运行产生的事件会被丢弃。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from codeagent.core.events import AgentEvent, EventType

__all__ = [
    "RuntimePhase",
    "RuntimeSnapshot",
    "RuntimeReducer",
    "reduce_runtime_event",
    "phase_label",
]


class RuntimePhase:
    """TUI 可观察的运行阶段名称。"""

    IDLE = "idle"
    WAITING_MODEL = "waiting_model"
    STREAMING = "streaming"
    TOOL_RUNNING = "tool_running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPACTING = "compacting"
    CANCELLING = "cancelling"
    ERROR = "error"
    RESTORING = "restoring"

    ALL = (
        IDLE,
        WAITING_MODEL,
        STREAMING,
        TOOL_RUNNING,
        AWAITING_CONFIRMATION,
        COMPACTING,
        CANCELLING,
        ERROR,
        RESTORING,
    )


@dataclass(frozen=True)
class RuntimeSnapshot:
    """一轮运行的可观测摘要，不写入会话 JSONL。"""

    phase: str = RuntimePhase.IDLE
    phase_started_at: float | None = None
    run_id: str | None = None
    session_id: str | None = None
    current_operation: str = ""
    elapsed_ms: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    completed_tool_ids: frozenset[str] = field(default_factory=frozenset)
    pending_confirmation: dict[str, Any] | None = None
    retryable: bool = False
    error_code: str | None = None
    error_message: str = ""
    cleanup_uncertain: bool = False
    side_effect_state: str = "none"
    context_tokens: int | None = None
    context_window: int | None = None
    context_stale: bool = False
    last_event_at: float | None = None

    def elapsed(self, now: float | None = None) -> int:
        """返回从当前阶段开始经过的毫秒数。"""
        if self.phase_started_at is None:
            return 0
        current = time.monotonic() if now is None else now
        return max(0, round((current - self.phase_started_at) * 1000))


_PHASE_LABELS = {
    RuntimePhase.IDLE: "空闲",
    RuntimePhase.WAITING_MODEL: "等待模型",
    RuntimePhase.STREAMING: "流式输出",
    RuntimePhase.TOOL_RUNNING: "工具执行",
    RuntimePhase.AWAITING_CONFIRMATION: "等待确认",
    RuntimePhase.COMPACTING: "压缩上下文",
    RuntimePhase.CANCELLING: "取消中",
    RuntimePhase.ERROR: "失败",
    RuntimePhase.RESTORING: "恢复会话",
}


def phase_label(phase: str) -> str:
    """把稳定阶段值转为状态栏文案。"""
    return _PHASE_LABELS.get(phase, phase)


class RuntimeReducer:
    """将 ``AgentEvent`` 归约为 ``RuntimeSnapshot``。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock

    def apply(self, snapshot: RuntimeSnapshot, event: AgentEvent) -> RuntimeSnapshot:
        """应用一个事件；明确过期的 session/run 事件保持原快照。"""
        metadata = dict(event.metadata or {})
        for field_name in (
            "session_id",
            "run_id",
            "tool_call_id",
            "operation_id",
            "phase",
            "elapsed_ms",
            "error_code",
            "retryable",
            "cleanup_uncertain",
            "side_effect_state",
        ):
            value = getattr(event, field_name, None)
            if value is not None:
                metadata.setdefault(field_name, value)
        session_id = event.session_id or metadata.get("session_id")
        run_id = event.run_id or metadata.get("run_id")
        if not self._belongs_to_snapshot(snapshot, session_id, run_id, event.type):
            return snapshot

        now = self._clock()
        current_session = str(session_id) if session_id is not None else snapshot.session_id
        current_run = str(run_id) if run_id is not None else snapshot.run_id
        next_snapshot = snapshot
        if current_session is not None and (
            snapshot.session_id is None
            or event.type in {EventType.SESSION_STARTED, EventType.RESTORE_STARTED}
        ):
            next_snapshot = replace(next_snapshot, session_id=current_session)
        if current_run is not None and (
            snapshot.run_id is None
            or event.type in {EventType.SESSION_STARTED, EventType.RESTORE_STARTED}
        ):
            next_snapshot = replace(next_snapshot, run_id=current_run)

        target = self._transition(next_snapshot, event, metadata)
        if target.phase != snapshot.phase:
            target = replace(target, phase_started_at=now, elapsed_ms=0)
        elif target.phase_started_at is not None:
            target = replace(target, elapsed_ms=max(0, round((now - target.phase_started_at) * 1000)))
        return replace(target, last_event_at=now)

    def _belongs_to_snapshot(
        self,
        snapshot: RuntimeSnapshot,
        session_id: Any,
        run_id: Any,
        event_type: str,
    ) -> bool:
        """旧事件不能覆盖当前界面；无上下文的旧事件保持兼容。"""
        if session_id is not None and snapshot.session_id is not None:
            if str(session_id) != snapshot.session_id and event_type not in {
                EventType.SESSION_STARTED,
                EventType.RESTORE_STARTED,
            }:
                return False
        if run_id is not None and snapshot.run_id is not None:
            if str(run_id) != snapshot.run_id:
                # 一个新的 session_started/restore 可以建立新的关联。
                return event_type in {EventType.SESSION_STARTED, EventType.RESTORE_STARTED}
        return True

    def _transition(
        self, snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]
    ) -> RuntimeSnapshot:
        event_type = event.type
        counts = dict(snapshot.tool_counts)
        completed_tool_ids = set(snapshot.completed_tool_ids)
        current_operation = snapshot.current_operation
        phase = snapshot.phase
        pending = snapshot.pending_confirmation
        retryable = snapshot.retryable
        error_code = snapshot.error_code
        error_message = snapshot.error_message
        cleanup_uncertain = snapshot.cleanup_uncertain
        side_effect_state = snapshot.side_effect_state
        context_tokens = snapshot.context_tokens
        context_window = snapshot.context_window
        context_stale = snapshot.context_stale

        if event_type == EventType.SESSION_STARTED:
            phase, current_operation = RuntimePhase.WAITING_MODEL, "等待模型响应"
            counts.clear()
            completed_tool_ids.clear()
            pending = None
            retryable = False
            error_code = None
            error_message = ""
            cleanup_uncertain = False
            side_effect_state = "none"
        elif event_type in {EventType.MODEL_REQUEST_STARTED, EventType.RETRY_STARTED}:
            phase = RuntimePhase.WAITING_MODEL
            current_operation = str(metadata.get("operation") or "等待模型响应")
            retryable = False
            error_code = None
            error_message = ""
        elif event_type == EventType.THINKING_DELTA:
            phase, current_operation = RuntimePhase.WAITING_MODEL, "模型推理"
        elif event_type == EventType.TEXT_DELTA:
            phase, current_operation = RuntimePhase.STREAMING, "接收模型回复"
        elif event_type in {EventType.TOOL_QUEUED, EventType.TOOL_STARTED, EventType.TOOL_PROGRESS}:
            phase = RuntimePhase.TOOL_RUNNING
            current_operation = str(
                metadata.get("tool_name")
                or (event.payload or {}).get("name")
                if isinstance(event.payload, dict)
                else metadata.get("operation")
                or "工具执行"
            )
            key = "queued" if event_type == EventType.TOOL_QUEUED else "running"
            counts[key] = counts.get(key, 0) + 1
            if event_type == EventType.TOOL_STARTED and counts.get("queued", 0):
                counts["queued"] -= 1
        elif event_type == EventType.CONFIRMATION_REQUESTED:
            phase, current_operation = RuntimePhase.AWAITING_CONFIRMATION, "等待确认"
            pending = dict(event.payload or {})
            counts["awaiting_confirmation"] = counts.get("awaiting_confirmation", 0) + 1
        elif event_type in {EventType.TOOL_FINISHED, EventType.TOOL_RESULT}:
            status = str(metadata.get("status") or "ok")
            tool_call_id = str(metadata.get("tool_call_id") or "")
            duplicate_result = (
                event_type == EventType.TOOL_RESULT
                and bool(tool_call_id)
                and tool_call_id in completed_tool_ids
            )
            if not duplicate_result:
                if counts.get("running", 0):
                    counts["running"] -= 1
                counts["completed" if status == "ok" else "failed"] = counts.get(
                    "completed" if status == "ok" else "failed", 0
                ) + 1
                if tool_call_id:
                    completed_tool_ids.add(tool_call_id)
            if status in {"timed_out", "cleanup_uncertain", "cancelled"}:
                cleanup_uncertain = cleanup_uncertain or status == "cleanup_uncertain"
                side_effect_state = "uncertain" if cleanup_uncertain else "possible"
            elif status not in {"ok", "rejected"}:
                side_effect_state = "possible"
            phase, current_operation = RuntimePhase.WAITING_MODEL, "等待后续模型回复"
            pending = None
        elif event_type == EventType.COMPACTION_STARTED:
            phase, current_operation = RuntimePhase.COMPACTING, "压缩上下文"
        elif event_type == EventType.COMPACTION_FINISHED:
            phase = RuntimePhase.IDLE if metadata.get("success", True) else RuntimePhase.ERROR
            current_operation = "" if phase == RuntimePhase.IDLE else "压缩失败"
            context_stale = False
            if phase == RuntimePhase.ERROR:
                error_code = str(metadata.get("error_code") or "compaction_failed")
                error_message = str(metadata.get("error_message") or "上下文压缩失败")
                retryable = bool(metadata.get("retryable", False))
        elif event_type == EventType.RESTORE_STARTED:
            phase, current_operation = RuntimePhase.RESTORING, "恢复会话"
            context_stale = True
        elif event_type == EventType.RESTORE_FINISHED:
            phase = RuntimePhase.IDLE if metadata.get("success", True) else RuntimePhase.ERROR
            current_operation = "" if phase == RuntimePhase.IDLE else "恢复失败"
            context_stale = False
            if phase == RuntimePhase.ERROR:
                error_code = str(metadata.get("error_code") or "restore_failed")
                error_message = str(metadata.get("error_message") or "会话恢复失败")
        elif event_type == EventType.CANCELLING:
            phase, current_operation = RuntimePhase.CANCELLING, "取消当前运行"
        elif event_type == EventType.RUN_CANCELLED:
            phase, current_operation = RuntimePhase.IDLE, ""
            side_effect_state = str(metadata.get("side_effect_state") or side_effect_state)
            cleanup_uncertain = bool(metadata.get("cleanup_uncertain", cleanup_uncertain))
            pending = None
        elif event_type == EventType.ERROR:
            phase, current_operation = RuntimePhase.ERROR, "处理失败"
            error_message = str(event.payload or metadata.get("error_message") or "发生错误")
            error_code = str(metadata.get("error_code") or "runtime_error")
            retryable = bool(metadata.get("retryable", False))
            cleanup_uncertain = bool(metadata.get("cleanup_uncertain", cleanup_uncertain))
            side_effect_state = str(metadata.get("side_effect_state") or side_effect_state)
            pending = None
        elif event_type == EventType.TURN_END:
            if metadata.get("terminal_phase") == RuntimePhase.ERROR or snapshot.phase == RuntimePhase.ERROR:
                phase, current_operation = RuntimePhase.ERROR, snapshot.current_operation
            else:
                phase, current_operation = RuntimePhase.IDLE, ""
                pending = None
        elif event_type == EventType.USAGE:
            usage = event.payload or {}
            context_tokens = _int_or_none(usage.get("input_tokens"))
            if "context_window" in metadata:
                context_window = _int_or_none(metadata.get("context_window"))
            context_stale = False

        return replace(
            snapshot,
            phase=phase,
            current_operation=current_operation,
            tool_counts=counts,
            completed_tool_ids=frozenset(completed_tool_ids),
            pending_confirmation=pending,
            retryable=retryable,
            error_code=error_code,
            error_message=error_message,
            cleanup_uncertain=cleanup_uncertain,
            side_effect_state=side_effect_state,
            context_tokens=context_tokens,
            context_window=context_window,
            context_stale=context_stale,
        )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def reduce_runtime_event(
    snapshot: RuntimeSnapshot,
    event: AgentEvent,
    clock: Callable[[], float] = time.monotonic,
) -> RuntimeSnapshot:
    """函数式归约入口，方便组件和离线测试直接使用。"""
    return RuntimeReducer(clock).apply(snapshot, event)
