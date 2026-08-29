"""Typed errors for persistence outcomes that cannot be confirmed."""

from __future__ import annotations

import asyncio

from codeagent.session.persistence.models import SessionRecoveryReport


class PersistenceUncertainError(RuntimeError):
    """A persistence operation may have partially completed."""


class PersistenceCancellationUncertainError(asyncio.CancelledError):
    """Cancellation arrived while a persistence result was still uncertain."""


class SessionRecoveryError(RuntimeError):
    """Session data cannot be activated safely; the report explains why."""

    def __init__(self, report: SessionRecoveryReport) -> None:
        self.report = report
        details = "; ".join(item.message for item in report.diagnostics)
        super().__init__(f"会话恢复不可用 [{report.session_id}]: {details}")


__all__ = [
    "PersistenceCancellationUncertainError",
    "PersistenceUncertainError",
    "SessionRecoveryError",
]
