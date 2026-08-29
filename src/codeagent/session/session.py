"""Stateful session facade assembled from focused session responsibilities."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context.contracts import TransformContext
from codeagent.core.context.diagnostics import ContextDiagnostics
from codeagent.core.context.preflight import ContextPreflightResult
from codeagent.core.contracts.ports import ApprovalPolicy
from codeagent.core.contracts.messages import Message
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.core.orchestration.loop import DEFAULT_RECURSION_LIMIT
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.session.compaction.summarizer import Summarizer
from codeagent.session.constants import (
    COMPACTION_RESERVE_TOKENS,
    DEFAULT_CONTEXT_WINDOW,
    SUMMARY_ID_PREFIX,
    SUMMARY_PREFIX,
)
from codeagent.session.contracts import SessionCloser
from codeagent.session.eventing import SessionEventMixin
from codeagent.session.lifecycle import SessionLifecycleMixin
from codeagent.session.persistence.models import SessionStore, UsageStats
from codeagent.session.runtime.controller import SessionRuntime
from codeagent.session.runtime.state import CommitStatus, RunOutcome, SessionBudgetState
from codeagent.session.compaction_runtime import SessionCompactionMixin
from codeagent.session.run_coordinator import SessionRunCoordinator
from codeagent.session.session_persistence import SessionPersistence
from codeagent.session.runtime.error_policy import friendly_error
from codeagent.session.events.bus import EventBus, Subscriber


class AgentSession(
    SessionEventMixin,
    SessionLifecycleMixin,
    SessionCompactionMixin,
):
    """Public facade for one stateful agent conversation."""

    def __init__(
        self,
        config: AgentLoopConfig,
        bus: EventBus,
        *,
        store: SessionStore | None = None,
        session_id: str | None = None,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        tool_timeout: float | None = None,
        confirmation_timeout: float | None = None,
        previous_session_id: str | None = None,
        summarizer: Summarizer | None = None,
        context_window: int | None = None,
        compact_budget: int | None = None,
        compaction_policy: CompactionPolicyConfig | None = None,
        defer_persistence: bool = False,
        persistence_options: dict[str, Any] | None = None,
        runtime_closer: SessionCloser | None = None,
        transform_context: TransformContext | None = None,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        self._config = config
        self._policy = policy
        self._bus = bus
        self._recursion_limit = recursion_limit
        self._tool_timeout = tool_timeout
        self._session_id = session_id or str(uuid.uuid4())
        self._previous_session_id = previous_session_id
        self._summarizer = summarizer
        self._context_window = self._resolve_context_window(config, context_window)
        self._runtime_closer = runtime_closer
        self._budget_state = SessionBudgetState()
        self._transform_context = transform_context
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        if compaction_policy is None:
            compaction_policy = CompactionPolicyConfig(compact_budget=compact_budget)
        elif compact_budget is not None:
            compaction_policy = replace(compaction_policy, compact_budget=compact_budget)
        self._compaction_policy = compaction_policy
        self._compact_budget = compact_budget
        self._compaction_gate = asyncio.Lock()
        self._last_compaction_fingerprint: tuple[Any, ...] | None = None
        self._last_compaction_failure_fingerprint: tuple[Any, ...] | None = None
        self._pending_compaction_budget: ContextBudgetSnapshot | None = None
        self._last_input_tokens: int | None = None
        self._persistence = SessionPersistence(
            store,
            self._session_id,
            defer_persistence=defer_persistence,
            persistence_options=persistence_options,
        )
        self._runtime = SessionRuntime(
            self._emit,
            self._on_run_event,
            session_id=self._session_id,
            confirmation_timeout=confirmation_timeout,
        )
        self._run_coordinator = SessionRunCoordinator(self)
        restored = self._persistence.load()
        self._history = restored.history
        self._summary: str | None = restored.summary
        self._summary_entry_id: str | None = restored.summary_entry_id
        self._prev_details: dict[str, Any] = restored.details
        self._last_input_tokens = restored.context_tokens
        self._bus.subscribe(self._on_internal_event)

    @staticmethod
    def _resolve_context_window(
        config: AgentLoopConfig,
        context_window: int | None,
    ) -> int:
        if context_window is None:
            model_window = getattr(getattr(config, "model", None), "context_window", None)
            return model_window if type(model_window) is int and model_window > 0 else DEFAULT_CONTEXT_WINDOW
        if type(context_window) is not int or context_window < 1:
            raise ValueError("context_window must be positive")
        return context_window

    @property
    def _current_task(self) -> asyncio.Task[None] | None:
        """Compatibility view; task ownership lives in SessionRuntime."""
        return self._runtime.current_task

    @_current_task.setter
    def _current_task(self, task: asyncio.Task[None] | None) -> None:
        self._runtime.current_task = task

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        return self._bus.subscribe(fn)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def history(self) -> list[Message]:
        return list(self._history)

    @property
    def usage(self) -> UsageStats:
        return self._persistence.usage

    @property
    def committed_usage(self) -> UsageStats:
        return self._persistence.usage

    @property
    def context_budget(self) -> ContextBudgetSnapshot | None:
        return self._budget_state.latest_estimate

    @property
    def context_diagnostics(self) -> ContextDiagnostics:
        """Return the latest runtime-only context diagnostic snapshot."""
        return self._budget_state.diagnostics

    @property
    def model_id(self) -> str | None:
        """Return the configured model id for diagnostic labeling."""
        model = getattr(self._config, "model", None)
        value = getattr(model, "model_id", None) or getattr(model, "id", None)
        return str(value) if value else None

    @property
    def context_preflight(self) -> ContextPreflightResult | None:
        return self._budget_state.latest_preflight

    @property
    def last_actual_usage(self) -> UsageStats | None:
        return self._budget_state.latest_actual_usage

    @property
    def is_persisted(self) -> bool:
        return self._persistence.persisted

    @property
    def context_tokens(self) -> int | None:
        return self._last_input_tokens

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def policy(self) -> ApprovalPolicy | None:
        return self._policy

    @property
    def summary(self) -> str | None:
        return self._summary

    @property
    def last_failure(self) -> dict[str, Any] | None:
        failure = self._runtime.last_failure
        return dict(failure) if failure is not None else None

    @property
    def last_outcome(self) -> RunOutcome | None:
        return self._runtime.last_outcome

    async def run(
        self,
        text: str,
        recursion_limit: int | None = None,
        *,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        return await self._run_coordinator.run(text, recursion_limit, policy)

    def _link_persistence_parents(self, messages: list[Message]) -> None:
        parent_id = self._summary_entry_id or (self._history[-1].id if self._history else None)
        for message in messages:
            if message.parent_id is None:
                message.parent_id = parent_id
            parent_id = message.id

    def _ensure_persisted(self) -> None:
        self._persistence.ensure_persisted()

    def ensure_persisted(self) -> None:
        """Persist a deferred session header before an explicit metadata edit."""
        self._ensure_persisted()

    def update_persistence_options(self, **options: Any) -> None:
        self._persistence.update_options(**options)

    def _rollback(self, before_ids: set[str]) -> None:
        self._history = [message for message in self._history if message.id in before_ids]

    def _rollback_status(self) -> CommitStatus:
        return (
            CommitStatus.UNCERTAIN
            if self._runtime.cleanup_uncertain
            else CommitStatus.ROLLED_BACK
        )

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        return friendly_error(exc)


__all__ = [
    "AgentSession",
    "COMPACTION_RESERVE_TOKENS",
    "DEFAULT_CONTEXT_WINDOW",
    "SUMMARY_ID_PREFIX",
    "SUMMARY_PREFIX",
]
