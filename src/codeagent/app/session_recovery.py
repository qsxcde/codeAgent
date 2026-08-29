"""Shared formatting for session recovery outcomes."""

from __future__ import annotations

from typing import Any


def format_recovery_report(
    report: Any,
    *,
    include_healthy: bool = True,
) -> str:
    """Format one recovery report consistently for CLI and TUI output."""
    if report.status == "healthy" and not include_healthy:
        return ""
    lines = [f"会话恢复诊断: {report.session_id} · 状态 {report.status}"]
    lines.append(
        f"有效消息: {report.valid_message_count} · 跳过记录: {report.skipped_record_count}"
    )
    if not report.diagnostics:
        lines.append("无恢复问题")
        return "\n".join(lines)
    lines.append("诊断:")
    for diagnostic in report.diagnostics:
        lines.append(f"- {diagnostic.code}: {diagnostic.message}")
        lines.append(f"  影响: {diagnostic.impact}")
        lines.append(f"  建议: {diagnostic.action}")
    return "\n".join(lines)


__all__ = ["format_recovery_report"]
