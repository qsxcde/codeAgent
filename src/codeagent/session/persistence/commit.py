"""Successful-turn persistence commit coordination."""

from __future__ import annotations

from collections.abc import Callable

from codeagent.core.messages import Message
from codeagent.session.persistence.models import (
    CompactionEntry,
    SessionStore,
    UsageStats,
)


class SessionCommitter:
    """Write explicitly successful session records to a store."""

    def __init__(
        self,
        store: SessionStore,
        session_id: str,
        *,
        ensure_persisted: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._session_id = session_id
        self._ensure_persisted = ensure_persisted or (lambda: None)

    def compaction(self, entry: CompactionEntry) -> str:
        self._ensure_persisted()
        return self._store.append_compaction(self._session_id, entry)  # type: ignore[return-value]

    def turn(
        self,
        messages: list[Message],
        usage: UsageStats,
        *,
        context_tokens: int | None,
    ) -> None:
        """Commit a successful turn; failed/cancelled turns never call this."""
        if not messages:
            return
        self._ensure_persisted()
        native_commit = getattr(self._store, "commit_turn", None)
        if callable(native_commit):
            native_commit(
                self._session_id,
                messages,
                usage,
                context_tokens=context_tokens,
            )
            return
        for message in messages:
            self._store.append_message(self._session_id, message)
        if _has_usage(usage):
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


def _has_usage(usage: UsageStats) -> bool:
    return any(
        (
            usage.input_tokens,
            usage.output_tokens,
            usage.reasoning_tokens,
            usage.cached_tokens,
        )
    )


__all__ = ["SessionCommitter"]
