"""Subagent 委派块：只展示有限的父级观测投影。"""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType

from ..primitives import Component, RichLine, _seg, _truncate, _wrap_rich
from ..subagent_result_stats import render_result_stats
from ..theme import ACCENT, DIM, ERROR, SUCCESS, TEXT, WARNING

_MAX_LABEL_CHARS = 96
_MAX_SUMMARY_CHARS = 96
_MAX_DIAGNOSTIC_CHARS = 512
_MAX_DETAIL_LINES = 12

_STATUS_LABELS = {
    "created": "已创建",
    "queued": "排队",
    "starting": "启动中",
    "running": "运行中",
    "waiting_confirmation": "等待确认",
    "cancelling": "取消中",
    "completed": "已完成",
    "failed": "失败",
    "timed_out": "已超时",
    "cancelled": "已取消",
    "rejected": "已拒绝",
    "abandoned": "已中断",
}
_TERMINAL = frozenset({"completed", "failed", "timed_out", "cancelled", "rejected", "abandoned"})
_PHASE_LABELS = {
    "starting": "启动中",
    "model_wait": "等待模型",
    "waiting_model": "等待模型",
    "tool_running": "工具执行",
    "awaiting_confirmation": "等待确认",
    "cancelling": "取消中",
    "completed": "完成",
    "recovered": "重启后不可恢复",
}


def _safe_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _metadata(event: AgentEvent) -> dict[str, Any]:
    metadata = dict(event.metadata or {})
    for name in (
        "delegation_id",
        "child_run_id",
        "subagent_status",
        "status",
        "profile",
        "task_label",
        "reason",
        "child_phase",
        "phase",
        "tool_name",
        "elapsed_ms",
        "reason_code",
        "error_code",
        "cleanup_uncertain",
        "child_sequence",
        "parent_sequence",
    ):
        value = getattr(event, name, None)
        if value is not None:
            metadata.setdefault(name, value)
    return metadata


def _int_or_none(value: Any) -> int | None:
    try:
        return max(0, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _payload_dict(event: AgentEvent) -> dict[str, Any]:
    return event.payload if isinstance(event.payload, dict) else {}


class SubagentBlock(Component):
    """Codex 风格的紧凑委派块，不保存子 Agent transcript。"""

    def __init__(
        self,
        delegation_id: str,
        *,
        task_label: str = "",
        profile: str = "",
    ) -> None:
        super().__init__()
        self.delegation_id = _safe_text(delegation_id, _MAX_LABEL_CHARS)
        self.parent_run_id: str | None = None
        self.task_label = _safe_text(task_label, _MAX_LABEL_CHARS)
        self.profile = _safe_text(profile, 40)
        self.status = "created"
        self.phase = ""
        self.child_run_id: str | None = None
        self.tool_name = ""
        self.elapsed_ms: int | None = None
        self.reason_code = ""
        self.reason_detail = ""
        self.summary = ""
        self.diagnostics = ""
        self.result_stats = ""
        self.cleanup_uncertain = False
        self.expanded = False
        self._last_sequence: int | None = None
        self._terminal = False

    @property
    def is_terminal(self) -> bool:
        return self._terminal

    def toggle_expand(self) -> None:
        self.expanded = not self.expanded
        self.touch()

    def cancel_from_parent(self, *, cleanup_uncertain: bool = False) -> None:
        """Close an active projection when the parent run is cancelled first."""
        if self._terminal:
            return
        self.status = "cancelled"
        self.reason_code = "parent_cancelled"
        self.cleanup_uncertain = self.cleanup_uncertain or cleanup_uncertain
        self._terminal = True
        self.touch()

    def apply_event(self, event: AgentEvent) -> bool:
        """Apply one correlated event, rejecting stale or terminal regressions."""
        metadata = _metadata(event)
        delegation_id = str(metadata.get("delegation_id") or "")
        if delegation_id != self.delegation_id:
            return False
        sequence = _int_or_none(metadata.get("parent_sequence"))
        if sequence is None:
            sequence = _int_or_none(metadata.get("child_sequence"))
        if sequence is not None and self._last_sequence is not None and sequence < self._last_sequence:
            return False

        payload = _payload_dict(event)
        status = _status_value(event, metadata, payload)
        if self._terminal:
            return False
        if status in _TERMINAL:
            self._terminal = True
        self.status = status
        self._last_sequence = sequence if sequence is not None else self._last_sequence
        self._update_metadata(metadata, payload)
        self.touch()
        return True

    def _update_metadata(self, metadata: dict[str, Any], payload: dict[str, Any]) -> None:
        if not self.task_label and metadata.get("task_label"):
            self.task_label = _safe_text(metadata["task_label"], _MAX_LABEL_CHARS)
        if not self.profile and metadata.get("profile"):
            self.profile = _safe_text(metadata["profile"], 40)
        child_run_id = metadata.get("child_run_id")
        if child_run_id:
            self.child_run_id = _safe_text(child_run_id, _MAX_LABEL_CHARS)
        phase = metadata.get("child_phase") or metadata.get("phase")
        if phase:
            self.phase = _safe_text(phase, 64)
        tool_name = metadata.get("tool_name") or payload.get("tool_name")
        if tool_name:
            self.tool_name = _safe_text(tool_name, 64)
        elapsed = _int_or_none(metadata.get("elapsed_ms") or payload.get("elapsed_ms"))
        if elapsed is not None:
            self.elapsed_ms = elapsed
        failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
        reason = metadata.get("reason_code") or metadata.get("error_code") or failure.get("reason_code")
        if reason:
            self.reason_code = _safe_text(reason, 96)
        reason_detail = metadata.get("reason") or payload.get("reason")
        if reason_detail:
            self.reason_detail = _safe_text(reason_detail, 96)
        summary = payload.get("summary")
        if summary:
            self.summary = _safe_text(summary, _MAX_SUMMARY_CHARS)
        diagnostics = payload.get("diagnostics")
        if isinstance(diagnostics, (list, tuple)):
            self.diagnostics = _safe_text("; ".join(str(item) for item in diagnostics), _MAX_DIAGNOSTIC_CHARS)
        elif diagnostics:
            self.diagnostics = _safe_text(diagnostics, _MAX_DIAGNOSTIC_CHARS)
        elif failure.get("message"):
            self.diagnostics = _safe_text(failure["message"], _MAX_DIAGNOSTIC_CHARS)
        self.result_stats = render_result_stats(payload)
        self.cleanup_uncertain = self.cleanup_uncertain or bool(
            metadata.get("cleanup_uncertain") or payload.get("cleanup_uncertain") or failure.get("cleanup_uncertain")
        )

    def render(self, width: int) -> list[RichLine]:
        width = max(1, width)
        status_label = _STATUS_LABELS.get(self.status, self.status or "未知")
        icon, icon_tag = _status_icon(self.status)
        summary_tag = (
            WARNING
            if self.cleanup_uncertain or self.status in {"waiting_confirmation", "cancelling"}
            else ERROR
            if self.status in _TERMINAL - {"completed"}
            else SUCCESS
            if self.status == "completed"
            else ACCENT
        )
        values = ["子 Agent", status_label]
        if self.task_label:
            values.append(self.task_label)
        if self.profile:
            values.append(self.profile)
        if self.phase and self.phase not in {self.status, "completed"}:
            values.append(_PHASE_LABELS.get(self.phase, self.phase))
        if self.tool_name:
            values.append(self.tool_name)
        if self.elapsed_ms is not None:
            values.append(_elapsed(self.elapsed_ms))
        if self.reason_code:
            values.append(self.reason_code)
        elif self.reason_detail:
            values.append(f"原因: {self.reason_detail}")
        if self.cleanup_uncertain:
            values.append("清理不确定")
        if self.summary and self.status in _TERMINAL:
            values.append(self.summary)
        line = [
            _seg("▼" if self.expanded else "▶", fg=DIM),
            _seg(" "),
            _seg(icon, fg=icon_tag),
            _seg(" "),
            _seg(" · ".join(values), fg=summary_tag),
        ]
        if not self.expanded:
            return [line]
        lines = [line]
        details = [
            f"委派 ID: {self.delegation_id}",
            f"子运行: {self.child_run_id or '—'}",
            f"阶段: {_PHASE_LABELS.get(self.phase, self.phase or '—')}",
        ]
        if self.summary:
            details.append(f"摘要: {self.summary}")
        if self.result_stats:
            details.append(f"统计: {self.result_stats}")
        if self.reason_code:
            details.append(f"错误码: {self.reason_code}")
        if self.reason_detail:
            details.append(f"原因: {self.reason_detail}")
        if self.diagnostics:
            details.append(f"诊断: {self.diagnostics}")
        for detail in details:
            if len(lines) >= _MAX_DETAIL_LINES:
                lines.append([_seg("… 委派详情已截断", fg=DIM)])
                break
            lines.extend(_wrap_rich(_truncate(detail, _MAX_DIAGNOSTIC_CHARS), max(1, width - 2), fg=TEXT))
        return lines[:_MAX_DETAIL_LINES]


def _status_value(event: AgentEvent, metadata: dict[str, Any], payload: dict[str, Any]) -> str:
    value = metadata.get("subagent_status") or metadata.get("status") or payload.get("subagent_status")
    if value:
        return _safe_text(value, 48)
    return {
        EventType.SUBAGENT_QUEUED: "queued",
        EventType.SUBAGENT_STARTED: "running",
        EventType.SUBAGENT_PROGRESS: "running",
        EventType.SUBAGENT_FINISHED: "failed",
    }.get(event.type, "created")


def _status_icon(status: str) -> tuple[str, str]:
    if status == "completed":
        return "✓", SUCCESS
    if status in _TERMINAL:
        return "✗", ERROR
    if status in {"waiting_confirmation", "cancelling"}:
        return "!", WARNING
    return "·", DIM


def _elapsed(value: int) -> str:
    return f"{value / 1000:.1f}s" if value >= 1000 else f"{value}ms"


__all__ = ["SubagentBlock"]
