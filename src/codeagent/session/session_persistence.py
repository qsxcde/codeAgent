"""Persistence coordination for AgentSession."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codeagent.core.contracts.events import AgentEvent
from codeagent.core.contracts.messages import Message
from codeagent.session.persistence.async_boundary import AsyncPersistenceBoundary
from codeagent.session.persistence.commit import SessionCommitter
from codeagent.session.persistence.models import (
    CompactionEntry,
    SessionStore,
    SessionRecoveryReport,
    SubagentRunRecord,
    UsageStats,
)
from codeagent.session.persistence.errors import SessionRecoveryError
from codeagent.session.persistence.subagent_runtime import SubagentRecordCoordinator


@dataclass(frozen=True)
class RestoredSessionState:
    """State loaded from a store before AgentSession starts running."""

    persisted: bool
    history: list[Message]
    summary: str | None
    summary_entry_id: str | None
    details: dict[str, Any]
    context_tokens: int | None
    subagent_records: list[SubagentRunRecord] = field(default_factory=list)


class SessionPersistence:
    """Own session-store loading and successful-turn commits.

    The coordinator deliberately does not own AgentSession history. Callers
    pass explicit messages and usage so failed or cancelled turns remain
    in-memory only.
    """

    def __init__(
        self,
        store: SessionStore | None,
        session_id: str,
        *,
        defer_persistence: bool = False,
        persistence_options: dict[str, Any] | None = None,
    ) -> None:
        self._store = store
        self._session_id = session_id
        self._defer_persistence = defer_persistence
        self._persistence_options = dict(persistence_options or {})
        self._async_boundary = AsyncPersistenceBoundary()
        self._persisted = store is None
        self._committer = (
            SessionCommitter(
                store,
                session_id,
                ensure_persisted=self.ensure_persisted,
            )
            if store is not None
            else None
        )
        self._recovery_report: SessionRecoveryReport | None = None
        self._subagent_runtime = SubagentRecordCoordinator(
            self._append_subagent_record,
            self._can_append_subagent_record,
        )

    @property
    def persisted(self) -> bool:
        return self._persisted

    @property
    def usage(self) -> UsageStats:
        if self._store is None or not self._persisted:
            return UsageStats()
        return self._store.load_usage(self._session_id)

    @property
    def recovery_report(self) -> SessionRecoveryReport:
        """Return the report captured while loading this session."""
        return self._recovery_report or SessionRecoveryReport(self._session_id, "healthy")

    @property
    def subagent_records(self) -> list[SubagentRunRecord]:
        """Return the current bounded parent-owned delegation projection."""
        return self._subagent_runtime.records

    @property
    def subagent_record_diagnostics(self) -> list[str]:
        return self._subagent_runtime.diagnostics

    def load(self) -> RestoredSessionState:
        """Load persisted context without creating deferred empty sessions."""
        if self._store is None:
            self._recovery_report = SessionRecoveryReport(self._session_id, "healthy")
            return RestoredSessionState(True, [], None, None, {}, None, [])

        report = self._recovery_report_for_store()
        missing = (
            report.status == "unavailable"
            and report.diagnostics
            and report.diagnostics[0].code == "missing_session"
        )
        if report.status == "unavailable" and not missing:
            self._recovery_report = report
            raise SessionRecoveryError(report)
        if missing and not self._defer_persistence:
            self._store.create(self._session_id, **self._persistence_options)
            store_ref = self._store.get(self._session_id)
            report = self._recovery_report_for_store()
        elif missing:
            store_ref = None
        else:
            try:
                store_ref = self._store.get(self._session_id)
            except (OSError, ValueError) as exc:
                report = self._recovery_report_for_store()
                self._recovery_report = report
                raise SessionRecoveryError(report) from exc
        self._persisted = store_ref is not None
        if not self._persisted:
            self._recovery_report = SessionRecoveryReport(self._session_id, "healthy")
            return RestoredSessionState(False, [], None, None, {}, None, [])

        self._recovery_report = report
        if not self._recovery_report.can_continue:
            raise SessionRecoveryError(self._recovery_report)
        state = self._store.load_context(self._session_id)
        saved_context = self._store.get_meta(self._session_id, "last_context_tokens")
        context_tokens = (
            saved_context
            if type(saved_context) is int and saved_context >= 0
            else None
        )
        loader = getattr(self._store, "load_subagent_records", None)
        records = list(loader(self._session_id)) if callable(loader) else []
        self._subagent_runtime.restore(records)
        return RestoredSessionState(
            True,
            state.messages,
            state.summary,
            state.entry_id,
            state.details,
            context_tokens,
            self._subagent_runtime.records,
        )

    def _recovery_report_for_store(self) -> SessionRecoveryReport:
        """Keep older injected stores usable while the report port rolls out."""
        if self._store is None:
            return SessionRecoveryReport(self._session_id, "healthy")
        reporter = getattr(self._store, "recovery_report", None)
        if not callable(reporter):
            return SessionRecoveryReport(self._session_id, "healthy")
        return reporter(self._session_id)

    def ensure_persisted(self) -> None:
        """Create a deferred session header on the first successful write."""
        if self._store is None or self._persisted:
            return
        if self._store.get(self._session_id) is None:
            self._store.create(self._session_id, **self._persistence_options)
        self._persisted = True

    def update_options(self, **options: Any) -> None:
        if not self._persisted:
            self._persistence_options.update(options)

    def append_compaction(self, entry: CompactionEntry) -> str:
        if self._committer is None:
            return entry.id
        return self._committer.compaction(entry)

    async def append_compaction_async(self, entry: CompactionEntry) -> str:
        """Append a compaction entry without blocking the event loop."""
        return await self._async_boundary.run(lambda: self.append_compaction(entry))

    def commit_turn(
        self,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        """Persist a successful turn; no-op for empty or non-persistent turns."""
        if self._committer is None:
            return
        self._committer.turn(messages, usage, context_tokens=context_tokens)

    async def commit_turn_async(
        self,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        """Commit one turn without blocking the event loop."""
        await self._async_boundary.run(
            lambda: self.commit_turn(
                messages,
                usage,
                context_tokens=context_tokens,
            )
        )

    async def drain_subagent_records(self) -> None:
        """Wait for all accepted record writes without blocking the loop."""
        await self._subagent_runtime.drain()

    def observe_subagent_event(self, event: AgentEvent, parent_run_id: str | None) -> None:
        """Forward one normalized event to the record coordinator."""
        self._subagent_runtime.observe(event, parent_run_id)

    def record_subagent_diagnostic(self, message: str) -> None:
        self._subagent_runtime.record_diagnostic(message)

    def _append_subagent_record(self, record: SubagentRunRecord) -> None:
        if self._committer is None:
            return
        self._committer.subagent(record)

    def _can_append_subagent_record(self) -> bool:
        return self._committer is not None and callable(
            getattr(self._store, "append_subagent_record", None)
        )
