"""TUI 运行态的事件转移规则。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.tool_status import ToolLifecycleStatus

from .runtime_state import RuntimePhase, RuntimeSnapshot
from .runtime_operations import compaction_finished, int_or_none, operation_finished
from .tool_lifecycle import is_terminal, normalize_status, transition_status


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
        return _confirmation_requested(snapshot, event, metadata)
    if event_type in {EventType.TOOL_FINISHED, EventType.TOOL_RESULT}:
        return _tool_finished(snapshot, event, metadata)
    if event_type == EventType.COMPACTION_STARTED:
        return replace(
            snapshot,
            phase=RuntimePhase.COMPACTING,
            current_operation="压缩上下文",
            compaction_trigger=str(metadata.get("trigger") or "manual"),
            compaction_status="running",
            compaction_reason=str(metadata.get("reason") or ""),
            compaction_before_tokens=int_or_none(metadata.get("input_tokens")),
            compaction_after_tokens=None,
            compaction_target_tokens=int_or_none(metadata.get("target_budget")),
        )
    if event_type == EventType.COMPACTION_FINISHED:
        return compaction_finished(snapshot, metadata)
    if event_type == EventType.RESTORE_STARTED:
        return replace(snapshot, phase=RuntimePhase.RESTORING, current_operation="恢复会话", context_stale=True)
    if event_type == EventType.RESTORE_FINISHED:
        return operation_finished(
            snapshot, metadata, "restore_failed", "恢复失败", "会话恢复失败"
        )
    if event_type == EventType.CANCELLING:
        return _simple_phase(snapshot, RuntimePhase.CANCELLING, "取消当前运行")
    if event_type == EventType.RUN_CANCELLED:
        cancelled_counts, cancelled_states = _cancel_active_tools(
            snapshot.tool_counts, snapshot.tool_states
        )
        return replace(
            snapshot,
            phase=RuntimePhase.IDLE,
            current_operation="",
            tool_counts=cancelled_counts,
            tool_states=cancelled_states,
            completed_tool_ids=frozenset(
                set(snapshot.completed_tool_ids)
                | {
                    call_id
                    for call_id, status in snapshot.tool_states.items()
                    if status in {"queued", "running", "awaiting_confirmation"}
                }
            ),
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
        tool_states={},
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
    event_type = event.type
    operation = str(
        metadata.get("tool_name")
        or (event.payload or {}).get("name")
        if isinstance(event.payload, dict)
        else metadata.get("operation")
        or "工具执行"
    )
    call_id = str(metadata.get("tool_call_id") or "")
    if event_type == EventType.TOOL_QUEUED:
        status = ToolLifecycleStatus.QUEUED
    else:
        status = ToolLifecycleStatus.RUNNING
    counts, states, _ = transition_status(
        snapshot.tool_counts, snapshot.tool_states, call_id, status
    )
    return replace(
        snapshot,
        phase=RuntimePhase.TOOL_RUNNING,
        current_operation=operation,
        tool_counts=counts,
        tool_states=states,
    )


def _confirmation_requested(
    snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]
) -> RuntimeSnapshot:
    call_id = str(
        (event.payload or {}).get("tool_call_id")
        if isinstance(event.payload, dict)
        else metadata.get("tool_call_id") or ""
    )
    counts, states, _ = transition_status(
        snapshot.tool_counts,
        snapshot.tool_states,
        call_id,
        ToolLifecycleStatus.AWAITING_CONFIRMATION,
    )
    if not call_id:
        counts = dict(snapshot.tool_counts)
        counts[ToolLifecycleStatus.AWAITING_CONFIRMATION] = (
            counts.get(ToolLifecycleStatus.AWAITING_CONFIRMATION, 0) + 1
        )
        states = dict(snapshot.tool_states)
    return replace(
        snapshot,
        phase=RuntimePhase.AWAITING_CONFIRMATION,
        current_operation="等待确认",
        tool_counts=counts,
        tool_states=states,
        pending_confirmation=dict(event.payload or {}),
    )


def _tool_finished(
    snapshot: RuntimeSnapshot, event: AgentEvent, metadata: dict[str, Any]
) -> RuntimeSnapshot:
    completed_tool_ids = set(snapshot.completed_tool_ids)
    status = normalize_status(metadata.get("status"), ToolLifecycleStatus.COMPLETED)
    tool_call_id = str(metadata.get("tool_call_id") or "")
    counts, states, changed = transition_status(
        snapshot.tool_counts,
        snapshot.tool_states,
        tool_call_id,
        status,
    )
    if changed and tool_call_id and is_terminal(status):
        completed_tool_ids.add(tool_call_id)
    cleanup_uncertain = snapshot.cleanup_uncertain or bool(
        metadata.get("cleanup_uncertain")
    ) or metadata.get("cleanup_status") in {"failed", "uncertain", "unsupported"}
    side_effect_state = snapshot.side_effect_state
    if status in {
        ToolLifecycleStatus.TIMED_OUT,
        ToolLifecycleStatus.CLEANUP_UNCERTAIN,
        ToolLifecycleStatus.CANCELLED,
    }:
        side_effect_state = "uncertain" if cleanup_uncertain else "possible"
    elif status not in {
        ToolLifecycleStatus.COMPLETED,
        ToolLifecycleStatus.REJECTED,
    }:
        side_effect_state = "possible"
    return replace(
        snapshot,
        phase=RuntimePhase.WAITING_MODEL,
        current_operation="等待后续模型回复",
        tool_counts=counts,
        tool_states=states,
        completed_tool_ids=frozenset(completed_tool_ids),
        pending_confirmation=None,
        cleanup_uncertain=cleanup_uncertain,
        side_effect_state=side_effect_state,
    )


def _cancel_active_tools(
    counts: dict[str, int], states: dict[str, str]
) -> tuple[dict[str, int], dict[str, str]]:
    updated_counts = dict(counts)
    updated_states = dict(states)
    for call_id, status in list(states.items()):
        if status not in {
            ToolLifecycleStatus.QUEUED,
            ToolLifecycleStatus.RUNNING,
            ToolLifecycleStatus.AWAITING_CONFIRMATION,
        }:
            continue
        updated_counts[status] = max(0, updated_counts.get(status, 0) - 1)
        updated_counts[ToolLifecycleStatus.CANCELLED] = (
            updated_counts.get(ToolLifecycleStatus.CANCELLED, 0) + 1
        )
        updated_states[call_id] = ToolLifecycleStatus.CANCELLED
    return updated_counts, updated_states


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
        context_window = int_or_none(metadata.get("context_window"))
    return replace(
        snapshot,
        context_tokens=int_or_none(usage.get("input_tokens")),
        context_window=context_window,
        context_stale=False,
    )
