"""Recovery reporting for the in-memory session backend."""

from __future__ import annotations

from codeagent.session.persistence.models import RecoveryDiagnostic, SessionRecoveryReport


class MemoryRecoveryMixin:
    """Expose the same recovery contract as the JSONL backend."""

    def recovery_report(self, session_id: str) -> SessionRecoveryReport:
        if not isinstance(session_id, str) or not session_id or "/" in session_id or "\\" in session_id:
            return SessionRecoveryReport(
                str(session_id),
                "unavailable",
                (
                    RecoveryDiagnostic(
                        "invalid_session_id",
                        "会话 id 格式无效",
                        "未读取任何会话数据",
                        "请使用列表中的单组件会话 id",
                    ),
                ),
            )
        sessions = getattr(self, "_sessions", {})
        if session_id not in sessions:
            return SessionRecoveryReport(
                session_id,
                "unavailable",
                (
                    RecoveryDiagnostic(
                        "missing_session",
                        f"会话不存在: {session_id}",
                        "没有可恢复的数据",
                        "请检查会话 id，或新建会话",
                    ),
                ),
            )
        messages = getattr(self, "_messages", {}).get(session_id, [])
        return SessionRecoveryReport(
            session_id,
            "healthy",
            valid_message_count=len(messages),
        )


__all__ = ["MemoryRecoveryMixin"]
