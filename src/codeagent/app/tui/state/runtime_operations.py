"""运行态中压缩、恢复等独立操作的状态归约。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .runtime_state import RuntimePhase, RuntimeSnapshot

__all__ = ["compaction_finished", "int_or_none", "operation_finished"]


def operation_finished(
    snapshot: RuntimeSnapshot,
    metadata: dict[str, Any],
    error_code: str,
    operation: str,
    error_message: str,
) -> RuntimeSnapshot:
    """完成一个非工具运行操作并保留失败诊断。"""
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


def compaction_finished(snapshot: RuntimeSnapshot, metadata: dict[str, Any]) -> RuntimeSnapshot:
    """归约压缩结果，供状态栏显示 token 前后变化。"""
    status = str(
        metadata.get("status")
        or ("compacted" if metadata.get("success", True) else "failed")
    )
    successful = status in {"compacted", "skipped"}
    values: dict[str, Any] = {
        "phase": RuntimePhase.IDLE if successful else RuntimePhase.ERROR,
        "current_operation": "" if successful else "压缩失败",
        "context_stale": False,
        "compaction_trigger": str(
            metadata.get("trigger") or snapshot.compaction_trigger or "manual"
        ),
        "compaction_status": status,
        "compaction_reason": str(
            metadata.get("reason_code") or metadata.get("error_code") or ""
        ),
        "compaction_before_tokens": int_or_none(
            metadata.get("before_input_tokens", snapshot.compaction_before_tokens)
        ),
        "compaction_after_tokens": int_or_none(metadata.get("after_input_tokens")),
        "compaction_target_tokens": int_or_none(
            metadata.get("target_budget", snapshot.compaction_target_tokens)
        ),
    }
    after_tokens = int_or_none(metadata.get("after_input_tokens"))
    if after_tokens is not None:
        values["context_tokens"] = after_tokens
    if not successful:
        values.update(
            error_code=str(metadata.get("error_code") or "compaction_failed"),
            error_message=str(metadata.get("error_message") or "上下文压缩失败"),
            retryable=bool(metadata.get("retryable", False)),
        )
    return replace(snapshot, **values)


def int_or_none(value: Any) -> int | None:
    """Convert optional event metadata to an integer."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
