"""Persistence coordination for AgentSession."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeagent.core.messages import Message
from codeagent.session.store_models import (
    CompactionEntry,
    SessionStore,
    UsageStats,
)


@dataclass(frozen=True)
class RestoredSessionState:
    """State loaded from a store before AgentSession starts running."""

    persisted: bool
    history: list[Message]
    summary: str | None
    summary_entry_id: str | None
    details: dict[str, Any]
    context_tokens: int | None


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
        self._persisted = store is None

    @property
    def persisted(self) -> bool:
        return self._persisted

    @property
    def usage(self) -> UsageStats:
        if self._store is None or not self._persisted:
            return UsageStats()
        return self._store.load_usage(self._session_id)

    def load(self) -> RestoredSessionState:
        """Load persisted context without creating deferred empty sessions."""
        if self._store is None:
            return RestoredSessionState(True, [], None, None, {}, None)

        store_ref = self._store.get(self._session_id)
        if store_ref is None and not self._defer_persistence:
            self._store.create(self._session_id, **self._persistence_options)
            store_ref = self._store.get(self._session_id)
        self._persisted = store_ref is not None
        if not self._persisted:
            return RestoredSessionState(False, [], None, None, {}, None)

        state = self._store.load_context(self._session_id)
        saved_context = self._store.get_meta(self._session_id, "last_context_tokens")
        context_tokens = (
            saved_context
            if type(saved_context) is int and saved_context >= 0
            else None
        )
        return RestoredSessionState(
            True,
            state.messages,
            state.summary,
            state.entry_id,
            state.details,
            context_tokens,
        )

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
        if self._store is None:
            return entry.id
        self.ensure_persisted()
        return self._store.append_compaction(self._session_id, entry)

    def commit_turn(
        self,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        """Persist a successful turn; no-op for empty or non-persistent turns."""
        if self._store is None or not messages:
            return
        self.ensure_persisted()
        for message in messages:
            self._store.append_message(self._session_id, message)
        if usage.input_tokens or usage.output_tokens:
            self._store.append_usage(
                self._session_id,
                {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "reasoning_tokens": usage.reasoning_tokens,
                    "cached_tokens": usage.cached_tokens,
                },
            )
            if context_tokens is not None:
                self._store.set_meta(
                    self._session_id,
                    "last_context_tokens",
                    context_tokens,
                )
