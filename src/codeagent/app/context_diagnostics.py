"""Human-readable rendering for the provider-independent context snapshot."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def format_context_diagnostics(diagnostics: Any | None) -> list[str]:
    """Render a stable, side-effect-free diagnostic block."""
    if diagnostics is None:
        diagnostics = _EMPTY_DIAGNOSTICS
    lines = ["上下文诊断:", f"模型: {diagnostics.model_id or '未知'}"]
    lines.append(_window_line(diagnostics))
    lines.append(_budget_line(diagnostics))
    if diagnostics.components:
        lines.append("预算组成:")
        lines.extend(
            f"  {name}: {_token(value)}"
            for name, value in diagnostics.components.items()
        )
    else:
        lines.append("预算组成: (未知)")
    lines.append(_actual_usage_line(diagnostics))
    lines.append(_preflight_line(diagnostics))
    lines.append(_compaction_line(diagnostics))
    lines.extend(_tool_result_lines(diagnostics))
    if diagnostics.last_failure:
        failure = diagnostics.last_failure
        lines.append(
            f"最近失败: {failure.get('code', 'unknown')} · "
            f"{failure.get('message', '未知原因')} · 阶段 {failure.get('phase', 'unknown')}"
        )
    return lines


def _window_line(diagnostics: Any) -> str:
    if diagnostics.context_window is None:
        return "窗口: 未知"
    certainty = {
        "known": "精确",
        "fallback": "fallback",
        "uncertain": "不确定",
        "unknown": "未知",
    }[diagnostics.window_certainty]
    return (
        f"窗口: {_token(diagnostics.context_window)} · "
        f"来源 {diagnostics.window_source} · {certainty}"
    )


def _budget_line(diagnostics: Any) -> str:
    if diagnostics.input_budget is None:
        return "预算: 未知"
    return (
        f"预算: 输入 {_token(diagnostics.input_tokens)} / "
        f"{_token(diagnostics.input_budget)} · 余量 {_token(diagnostics.headroom)}"
    )


def _actual_usage_line(diagnostics: Any) -> str:
    if diagnostics.actual_input_tokens is None:
        return "实际用量: (未发生或未知)"
    return (
        f"实际用量: 输入 {_token(diagnostics.actual_input_tokens)} · "
        f"输出 {_token(diagnostics.actual_output_tokens)} · "
        f"缓存 {_token(diagnostics.actual_cached_tokens)}"
    )


def _preflight_line(diagnostics: Any) -> str:
    if diagnostics.preflight_status is None:
        return "Preflight: (未发生)"
    suffix = f" · {diagnostics.preflight_reason}" if diagnostics.preflight_reason else ""
    return f"Preflight: {diagnostics.preflight_status}{suffix}"


def _compaction_line(diagnostics: Any) -> str:
    compaction = diagnostics.compaction
    if compaction is None:
        return "最近压缩: (未发生)"
    parts = [
        f"最近压缩: {compaction.status}",
        f"触发 {compaction.trigger}",
    ]
    if compaction.reason_code:
        parts.append(f"原因 {compaction.reason_code}")
    if compaction.before_input_tokens is not None:
        parts.append(f"前 {_token(compaction.before_input_tokens)}")
    if compaction.after_input_tokens is not None:
        parts.append(f"后 {_token(compaction.after_input_tokens)}")
    if compaction.target_tokens is not None:
        parts.append(f"目标 {_token(compaction.target_tokens)}")
    if compaction.cropped_range:
        parts.append(f"裁剪 {compaction.cropped_range[0]}..{compaction.cropped_range[1]}")
    if compaction.retained_range:
        parts.append(f"保留 {compaction.retained_range[0]}..{compaction.retained_range[1]}")
    return " · ".join(parts)


def _tool_result_lines(diagnostics: Any) -> list[str]:
    if not diagnostics.tool_results:
        return ["工具结果治理: (无)"]
    lines = ["工具结果治理:"]
    for result in diagnostics.tool_results:
        call_id = result.tool_call_id or "unknown"
        lines.append(
            f"  {call_id}: {result.action} · "
            f"{_token(result.shown_bytes)} / {_token(result.original_bytes)} B · "
            f"{result.status}"
        )
    return lines


def _token(value: int | None) -> str:
    return "未知" if value is None else f"{value:,}"


_EMPTY_DIAGNOSTICS = SimpleNamespace(
    model_id=None,
    context_window=None,
    window_source="unknown",
    window_certainty="unknown",
    input_budget=None,
    input_tokens=None,
    headroom=None,
    components={},
    actual_input_tokens=None,
    actual_output_tokens=None,
    actual_cached_tokens=None,
    preflight_status=None,
    preflight_reason=None,
    compaction=None,
    tool_results=(),
    last_failure=None,
)


__all__ = ["format_context_diagnostics"]
