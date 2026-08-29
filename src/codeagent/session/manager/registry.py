"""Resident-session registry helpers for ``SessionManager``."""

from __future__ import annotations

from typing import Any

from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.session.constants import DEFAULT_CONTEXT_WINDOW
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.session.events.bus import EventBus
from codeagent.session.persistence.models import SessionRef
from codeagent.session.session import AgentSession


class SessionManagerRegistry:
    """Adopt session shells and enforce the resident-session bound."""

    def _last_user_message_id(self, session_id: str) -> str:
        messages = self._store.load_messages(session_id)
        for message in reversed(messages):
            if message.role == "user":
                return message.id
        raise ValueError("会话没有可分叉的用户消息")

    def _halt_current(self) -> None:
        current = self.current
        if current is not None:
            current.abort()

    async def _halt_current_and_wait(self) -> None:
        current = self.current
        if current is None:
            return
        cancel_and_wait = getattr(current, "cancel_and_wait", None)
        if callable(cancel_and_wait):
            result = cancel_and_wait()
            if hasattr(result, "__await__"):
                await result
            return
        current.abort()
        wait_for_idle = getattr(current, "wait_for_idle", None)
        if callable(wait_for_idle):
            result = wait_for_idle()
            if hasattr(result, "__await__"):
                await result

    def _adopt(
        self,
        session_id: str,
        *,
        previous_session_id: str | None = None,
        defer_persistence: bool = False,
        persistence_options: dict[str, Any] | None = None,
    ) -> AgentSession:
        config = self._config
        context_window = self._context_window
        if self._store is not None and self._session_config_factory is not None:
            ref = self._store.get(session_id)
            if ref is not None and ref.model:
                config = self._session_config_factory(ref)
                model_window = getattr(getattr(config, "model", None), "context_window", None)
                if type(model_window) is int and model_window > 0:
                    context_window = model_window
                self._config, self._context_window = config, context_window
                self._model, self._effort = ref.model, ref.effort
        session = AgentSession(
            config,
            EventBus(),
            store=self._store,
            session_id=session_id,
            recursion_limit=self._recursion_limit,
            tool_timeout=self._tool_timeout,
            confirmation_timeout=self._confirmation_timeout,
            previous_session_id=previous_session_id,
            summarizer=self._summarizer,
            context_window=context_window,
            compact_budget=self._compact_budget,
            compaction_policy=self._compaction_policy,
            defer_persistence=defer_persistence,
            persistence_options=persistence_options,
            policy=self._policy,
        )
        for fn, unsubs in self._subscribers:
            for unsubscribe in unsubs:
                unsubscribe()
            unsubs.clear()
            unsubs.append(session.subscribe(fn))
        self._sessions[session_id] = session
        self._current_id = session_id
        self._touch_session(session_id)
        self._evict_idle_sessions()
        return session

    def _touch_session(self, session_id: str) -> None:
        self._access_counter += 1
        self._session_access[session_id] = self._access_counter

    def _evict_idle_sessions(self) -> None:
        while len(self._sessions) > self._max_resident_sessions:
            candidates = [sid for sid in self._sessions if sid != self._current_id]
            if not candidates:
                return
            victim = min(candidates, key=lambda sid: self._session_access.get(sid, 0))
            self._sessions.pop(victim, None)
            self._session_access.pop(victim, None)


__all__ = ["SessionManagerRegistry"]
