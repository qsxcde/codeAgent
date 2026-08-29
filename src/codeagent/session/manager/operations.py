"""Lifecycle operations delegated by ``SessionManager``."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import TYPE_CHECKING

from codeagent.core.contracts.ports import ApprovalPolicy
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.session.compaction.summarizer import Summarizer
from codeagent.session.contracts import SessionCloser
from codeagent.session.persistence.models import SessionRef, SessionStore
from codeagent.session.persistence.codec import normalize_title

if TYPE_CHECKING:
    from codeagent.session.session import AgentSession


class SessionManagerOperations:
    """Create, switch, fork, configure and close active sessions."""

    def create(self, *, parent_session: str | None = None) -> AgentSession:
        self._halt_current()
        return self._adopt(
            str(uuid.uuid4()),
            defer_persistence=True,
            persistence_options={
                "parent_session": parent_session,
                "model": self._model,
                "effort": self._effort,
            },
        )

    async def create_async(self, *, parent_session: str | None = None) -> AgentSession:
        await self._halt_current_and_wait()
        return self._adopt(
            str(uuid.uuid4()),
            defer_persistence=True,
            persistence_options={
                "parent_session": parent_session,
                "model": self._model,
                "effort": self._effort,
            },
        )

    def switch(self, session_id: str) -> AgentSession:
        self._halt_current()
        self._ensure_session_exists(session_id)
        return self._adopt(session_id)

    async def switch_async(self, session_id: str) -> AgentSession:
        await self._halt_current_and_wait()
        self._ensure_session_exists(session_id)
        return self._adopt(session_id)

    def _ensure_session_exists(self, session_id: str) -> None:
        if self._store is not None and self._store.get(session_id) is None:
            raise ValueError(f"会话不存在: {session_id}")

    def continue_recent(self) -> AgentSession:
        refs = self.list()
        return self.create() if not refs else self.switch(refs[-1].id)

    def rename(self, session_id: str, title: str) -> str:
        """Persist a bounded display title without changing session activity."""
        normalized = normalize_title(title)
        if not normalized:
            raise ValueError("标题不能为空")
        if self._store is None:
            raise ValueError("设置会话标题需要持久化会话")
        if self._store.get(session_id) is None:
            session = self._sessions.get(session_id)
            ensure_persisted = getattr(session, "ensure_persisted", None)
            if not callable(ensure_persisted):
                raise ValueError(f"会话不存在: {session_id}")
            ensure_persisted()
            if self._store.get(session_id) is None:
                raise ValueError(f"会话不存在: {session_id}")
        self._store.set_meta(session_id, "name", normalized)
        ref = self._store.get(session_id)
        if ref is None:  # pragma: no cover - store contract guarantees the session
            raise ValueError(f"会话不存在: {session_id}")
        return ref.title

    async def continue_recent_async(self) -> AgentSession:
        refs = self.list()
        return await self.create_async() if not refs else await self.switch_async(refs[-1].id)

    def fork(self, session_id: str, message_id: str | None = None) -> AgentSession:
        self._ensure_fork_source(session_id)
        message_id = message_id or self._last_user_message_id(session_id)
        self._halt_current()
        new_id = str(uuid.uuid4())
        self._store.fork(session_id, message_id, new_id)
        return self._adopt(new_id, previous_session_id=session_id)

    async def fork_async(
        self,
        session_id: str,
        message_id: str | None = None,
    ) -> AgentSession:
        self._ensure_fork_source(session_id)
        message_id = message_id or self._last_user_message_id(session_id)
        await self._halt_current_and_wait()
        new_id = str(uuid.uuid4())
        self._store.fork(session_id, message_id, new_id)
        return self._adopt(new_id, previous_session_id=session_id)

    def _ensure_fork_source(self, session_id: str) -> None:
        if self._store is None:
            raise ValueError("分叉需要持久化会话(当前无会话存储)")
        if self._store.get(session_id) is None:
            raise ValueError(f"会话不存在: {session_id}")

    def replace_config(
        self,
        config: AgentLoopConfig,
        *,
        model: str = "",
        effort: str = "",
        context_window: int | None = None,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        self._halt_current()
        self._config = config
        if policy is not None:
            self._policy = policy
        self._model, self._effort = model, effort
        context_window = self._config_context_window(config, context_window)
        if context_window is not None:
            if type(context_window) is not int or context_window < 1:
                raise ValueError("context_window must be positive")
            self._context_window = context_window
        for session in self._sessions.values():
            session.replace_config(config, policy=policy)
            if context_window is not None:
                session.set_context_window(context_window)
            session.update_persistence_options(model=model, effort=effort)
        if self._can_write_model_change():
            self._store.append_model_change(self._current_id, model=model, effort=effort)

    @staticmethod
    def _config_context_window(
        config: AgentLoopConfig,
        context_window: int | None,
    ) -> int | None:
        if context_window is not None:
            return context_window
        value = getattr(getattr(config, "model", None), "context_window", None)
        return value if type(value) is int and value > 0 else None

    def _can_write_model_change(self) -> bool:
        return bool(
            self._store is not None
            and self._current_id is not None
            and self.current is not None
            and self.current.is_persisted
        )

    async def replace_config_async(
        self,
        config: AgentLoopConfig,
        *,
        model: str = "",
        effort: str = "",
        context_window: int | None = None,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        await self._halt_current_and_wait()
        self.replace_config(
            config,
            model=model,
            effort=effort,
            context_window=context_window,
            policy=policy,
        )

    def dispose(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        self._session_access.pop(session_id, None)
        if session is not None:
            session.abort()
        if self._current_id == session_id:
            self._current_id = None

    async def dispose_async(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            await self._wait_session(session)
        self.dispose(session_id)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_resources())
        await asyncio.shield(self._close_task)

    async def _close_resources(self) -> None:
        for session in self._sessions.values():
            await self._wait_session(session)
        close_summarizer = getattr(self._summarizer, "aclose", None)
        if callable(close_summarizer):
            result = close_summarizer()
            if inspect.isawaitable(result):
                await result
        if self._runtime_closer is not None:
            result = self._runtime_closer()
            if inspect.isawaitable(result):
                await result

    @staticmethod
    async def _wait_session(session: AgentSession) -> None:
        cancel_and_wait = getattr(session, "cancel_and_wait", None)
        if callable(cancel_and_wait):
            result = cancel_and_wait()
            if inspect.isawaitable(result):
                await result
        else:
            session.abort()

    def close_sync(self) -> asyncio.Task[None] | None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
            return None
        return asyncio.create_task(self.close())

    def list(self) -> list[SessionRef]:
        return [] if self._store is None else self._store.list()


__all__ = ["SessionManagerOperations"]
