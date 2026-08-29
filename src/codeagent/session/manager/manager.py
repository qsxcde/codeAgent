"""Public manager for resident session lifecycles."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from codeagent.core.contracts.ports import AgentTool, ApprovalPolicy
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.session.compaction.summarizer import Summarizer
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.session.constants import DEFAULT_CONTEXT_WINDOW
from codeagent.session.contracts import SessionCloser
from codeagent.session.events.bus import EventBus, Subscriber
from codeagent.session.manager.archive import SessionManagerArchiveOperations
from codeagent.session.manager.operations import SessionManagerOperations
from codeagent.session.manager.registry import SessionManagerRegistry
from codeagent.session.persistence.models import SessionRef, SessionStore
from codeagent.session.session import AgentSession


class SessionManager(
    SessionManagerOperations,
    SessionManagerArchiveOperations,
    SessionManagerRegistry,
):
    """Manage one active session and a bounded resident-session registry."""

    def __init__(
        self,
        config: AgentLoopConfig,
        store: SessionStore | None = None,
        *,
        model: str = "",
        effort: str = "",
        recursion_limit: int = 50,
        tool_timeout: float | None = None,
        confirmation_timeout: float | None = None,
        summarizer: Summarizer | None = None,
        context_window: int | None = None,
        compact_budget: int | None = None,
        compaction_policy: CompactionPolicyConfig | None = None,
        runtime_closer: SessionCloser | None = None,
        policy: ApprovalPolicy | None = None,
        session_config_factory: Callable[[SessionRef], AgentLoopConfig] | None = None,
        max_resident_sessions: int = 32,
    ) -> None:
        if type(max_resident_sessions) is not int or max_resident_sessions < 1:
            raise ValueError("max_resident_sessions must be positive")
        self._config = config
        self._policy = policy
        self._store = store
        self._model = model
        self._effort = effort
        self._recursion_limit = recursion_limit
        self._tool_timeout = tool_timeout
        self._confirmation_timeout = confirmation_timeout
        self._summarizer = summarizer
        self._context_window = self._resolve_context_window(config, context_window)
        self._compact_budget = compact_budget
        self._compaction_policy = compaction_policy
        self._runtime_closer = runtime_closer
        self._session_config_factory = session_config_factory
        self._max_resident_sessions = max_resident_sessions
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._sessions: dict[str, AgentSession] = {}
        self._session_access: dict[str, int] = {}
        self._access_counter = 0
        self._current_id: str | None = None
        self._subscribers: list[tuple[Subscriber, list[Callable[[], None]]]] = []

    @staticmethod
    def _resolve_context_window(
        config: AgentLoopConfig,
        context_window: int | None,
    ) -> int:
        if context_window is None:
            value = getattr(getattr(config, "model", None), "context_window", None)
            return value if type(value) is int and value > 0 else DEFAULT_CONTEXT_WINDOW
        if type(context_window) is not int or context_window < 1:
            raise ValueError("context_window must be positive")
        return context_window

    @property
    def current(self) -> AgentSession | None:
        if self._current_id is None:
            return None
        return self._sessions.get(self._current_id)

    @property
    def tools(self) -> list[AgentTool]:
        return list(getattr(self._config, "tools", []))

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        unsubs: list[Callable[[], None]] = []
        current = self.current
        if current is not None:
            unsubs.append(current.subscribe(fn))
        self._subscribers.append((fn, unsubs))

        def unsubscribe() -> None:
            for cancel in unsubs:
                cancel()
            self._subscribers.remove((fn, unsubs))

        return unsubscribe


__all__ = ["SessionManager"]
