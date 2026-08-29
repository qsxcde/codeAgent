"""TUI 运行态的稳定值对象和阶段文案。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["RuntimePhase", "RuntimeSnapshot", "phase_label"]


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
    compaction_trigger: str | None = None
    compaction_status: str | None = None
    compaction_reason: str | None = None
    compaction_before_tokens: int | None = None
    compaction_after_tokens: int | None = None
    compaction_target_tokens: int | None = None
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
