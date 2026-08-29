"""TUI 运行态的事件转移规则。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType

from .runtime_state import RuntimePhase, RuntimeSnapshot


def transition(
    snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]
) -> RuntimeSnapshot:
    """应用一个事件的业务转移，不处理会话/运行关联和时钟。"""
    event_type = event.type
    if event_type == EventType.SESSION_STARTED:
        return _session_started(snapshot)
    if event_type in {EventType.MODEL_REQUEST_STARTED, EventType.RETRY_STARTED}:
        return _model_started(snapshot, metadata)
    if event_type == EventType.THINKING_DELTA:
        return _simple_phase(snapshot, RuntimePhase.WAITING_MODEL, "模型推理")
    if event_type == EventType.TEXT_DELTA:
        return _simple_phase(snapshot, RuntimePhase.STREAMING, "接收模型回复")
    if event_type in {EventType.TOOL_QUEUED, EventType.TOOL_STARTED, EventType.TOOL_PROGRESS}:
        return _tool_progress(snapshot, event, metadata)
    if event_type == EventType.CONFIRMATION_REQUESTED:
        return _confirmation_requested(snapshot, event)
    if event_type in {EventType.TOOL_FINISHED, EventType.TOOL_RESULT}:
        return _tool_finished(snapshot, event, metadata)
    if event_type == EventType.COMPACTION_STARTED:
        return _simple_phase(snapshot, RuntimePhase.COMPACTING, "压缩上下文")
    if event_type == EventType.COMPACTION_FINISHED:
        return _operation_finished(
            snapshot, metadata, "compaction_failed", "压缩失败", "上下文压缩失败"
        )
    if event_type == EventType.RESTORE_STARTED:
        return replace(snapshot, phase=RuntimePhase.RESTORING, current_operation="恢复会话", context_stale=True)
    if event_type == EventType.RESTORE_FINISHED:
        return _operation_finished(
            snapshot, metadata, "restore_failed", "恢复失败", "会话恢复失败"
        )
    if event_type == EventType.CANCELLING:
        return _simple_phase(snapshot, RuntimePhase.CANCELLING, "取消当前运行")
    if event_type == EventType.RUN_CANCELLED:
        return replace(
            snapshot,
            phase=RuntimePhase.IDLE,
            current_operation="",
            side_effect_state=str(metadata.get("side_effect_state") or snapshot.side_effect_state),
            cleanup_uncertain=bool(metadata.get("cleanup_uncertain", snapshot.cleanup_uncertain)),
            pending_confirmation=None,
        )
    if event_type == EventType.ERROR:
        return _error(snapshot, event, metadata)
    if event_type == EventType.TURN_END:
        return _turn_end(snapshot, metadata)
    if event_type == EventType.USAGE:
        return _usage(snapshot, event, metadata)
    return snapshot


def _session_started(snapshot: RuntimeSnapshot) -> RuntimeSnapshot:
    return replace(
        snapshot,
        phase=RuntimePhase.WAITING_MODEL,
        current_operation="等待模型响应",
        tool_counts={},
        completed_tool_ids=frozenset(),
        pending_confirmation=None,
        retryable=False,
        error_code=None,
        error_message="",
        cleanup_uncertain=False,
        side_effect_state="none",
    )


def _model_started(snapshot: RuntimeSnapshot, metadata: dict[str, Any]) -> RuntimeSnapshot:
    return replace(
        snapshot,
        phase=RuntimePhase.WAITING_MODEL,
        current_operation=str(metadata.get("operation") or "等待模型响应"),
        retryable=False,
        error_code=None,
        error_message="",
    )


def _simple_phase(snapshot: RuntimeSnapshot, phase: str, operation: str) -> RuntimeSnapshot:
    return replace(snapshot, phase=phase, current_operation=operation)


def _tool_progress(
    snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]
) -> RuntimeSnapshot:
    counts = dict(snapshot.tool_counts)
    event_type = event.type
    operation = str(
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
    return replace(snapshot, phase=RuntimePhase.TOOL_RUNNING, current_operation=operation, tool_counts=counts)


def _confirmation_requested(snapshot: RuntimeSnapshot, event: AgentEvent) -> RuntimeSnapshot:
    counts = dict(snapshot.tool_counts)
    counts["awaiting_confirmation"] = counts.get("awaiting_confirmation", 0) + 1
    return replace(
        snapshot,
        phase=RuntimePhase.AWAITING_CONFIRMATION,
        current_operation="等待确认",
        tool_counts=counts,
        pending_confirmation=dict(event.payload or {}),
    )


def _tool_finished(
    snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]
) -> RuntimeSnapshot:
    counts = dict(snapshot.tool_counts)
    completed_tool_ids = set(snapshot.completed_tool_ids)
    status = str(metadata.get("status") or "ok")
    tool_call_id = str(metadata.get("tool_call_id") or "")
    duplicate = event.type == EventType.TOOL_RESULT and bool(tool_call_id) and tool_call_id in completed_tool_ids
    if not duplicate:
        if counts.get("running", 0):
            counts["running"] -= 1
        key = "completed" if status == "ok" else "failed"
        counts[key] = counts.get(key, 0) + 1
        if tool_call_id:
            completed_tool_ids.add(tool_call_id)
    cleanup_uncertain = snapshot.cleanup_uncertain or status == "cleanup_uncertain"
    side_effect_state = snapshot.side_effect_state
    if status in {"timed_out", "cleanup_uncertain", "cancelled"}:
        side_effect_state = "uncertain" if cleanup_uncertain else "possible"
    elif status not in {"ok", "rejected"}:
        side_effect_state = "possible"
    return replace(
        snapshot,
        phase=RuntimePhase.WAITING_MODEL,
        current_operation="等待后续模型回复",
        tool_counts=counts,
        completed_tool_ids=frozenset(completed_tool_ids),
        pending_confirmation=None,
        cleanup_uncertain=cleanup_uncertain,
        side_effect_state=side_effect_state,
    )


def _operation_finished(
    snapshot: RuntimeSnapshot,
    metadata: dict[str, Any],
    error_code: str,
    operation: str,
    error_message: str,
) -> RuntimeSnapshot:
    success = metadata.get("success", True)
    phase = RuntimePhase.IDLE if success else RuntimePhase.ERROR
    values: dict[str, Any] = {
        "phase": phase,
        "current_operation": "" if success else operation,
        "context_stale": False,
    }
    if not success:
        values.update(
            error_code=str(metadata.get("error_code") or error_code),
            error_message=str(metadata.get("error_message") or error_message),
        )
        if error_code == "compaction_failed":
            values["retryable"] = bool(metadata.get("retryable", False))
    return replace(snapshot, **values)


def _error(snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]) -> RuntimeSnapshot:
    return replace(
        snapshot,
        phase=RuntimePhase.ERROR,
        current_operation="处理失败",
        error_message=str(event.payload or metadata.get("error_message") or "发生错误"),
        error_code=str(metadata.get("error_code") or "runtime_error"),
        retryable=bool(metadata.get("retryable", False)),
        cleanup_uncertain=bool(metadata.get("cleanup_uncertain", snapshot.cleanup_uncertain)),
        side_effect_state=str(metadata.get("side_effect_state") or snapshot.side_effect_state),
        pending_confirmation=None,
    )


def _turn_end(snapshot: RuntimeSnapshot, metadata: dict[str, Any]) -> RuntimeSnapshot:
    if metadata.get("terminal_phase") == RuntimePhase.ERROR or snapshot.phase == RuntimePhase.ERROR:
        return replace(snapshot, phase=RuntimePhase.ERROR, current_operation=snapshot.current_operation)
    return replace(snapshot, phase=RuntimePhase.IDLE, current_operation="", pending_confirmation=None)


def _usage(snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]) -> RuntimeSnapshot:
    usage = event.payload or {}
    context_window = snapshot.context_window
    if "context_window" in metadata:
        context_window = _int_or_none(metadata.get("context_window"))
    return replace(
        snapshot,
        context_tokens=_int_or_none(usage.get("input_tokens")),
        context_window=context_window,
        context_stale=False,
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
