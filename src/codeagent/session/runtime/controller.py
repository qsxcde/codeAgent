"""Lifecycle controller for one session run."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

from codeagent.core import Agent
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.context.model import AgentContext
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.session.persistence.models import UsageStats
from codeagent.session.runtime.confirmation import ConfirmationCoordinator
from codeagent.session.runtime.event_mapper import SideEffectObserver
from codeagent.session.runtime.state import (
    CommitStatus,
    RunOutcome,
    RunPhase,
    RunState,
    RuntimeFailure,
)
from codeagent.session.runtime.execution import SessionExecutionMixin
from codeagent.session.runtime.event_lifecycle import RuntimeEventMixin

AgentFactory = Callable[[AgentContext, AgentLoopConfig, int], Agent]


def _default_agent_factory(
    context: AgentContext, config: AgentLoopConfig, recursion_limit: int
) -> Agent:
    return Agent(context, config, recursion_limit=recursion_limit)


class SessionRuntime(RuntimeEventMixin, SessionExecutionMixin):
    """Own mutable state associated with one active AgentSession run."""

    def __init__(
        self,
        emit: Callable[[AgentEvent, str | None], None],
        event_handler: Callable[[AgentEvent, str], None] | None = None,
        agent_factory: AgentFactory | None = None,
        session_id: str | None = None,
        confirmation_timeout: float | None = None,
    ) -> None:
        self._emit = emit
        self._event_handler = event_handler
        self._agent_factory = agent_factory or _default_agent_factory
        self._session_id = session_id
        self._confirmation_timeout = confirmation_timeout
        self.inject_queue: asyncio.Queue[str] = asyncio.Queue()
        self.confirmation = ConfirmationCoordinator()
        self.current_task: asyncio.Task[None] | None = None
        self._state = RunState(session_id=session_id)
        self._side_effects = SideEffectObserver()
        self.last_failure: dict[str, Any] | None = None
        self.last_outcome: RunOutcome | None = None
        self.turn_usage = UsageStats()
        self.agent: Agent | None = None

    @property
    def agent_factory(self) -> AgentFactory:
        return self._agent_factory

    @property
    def confirm_queue(self) -> asyncio.Queue[tuple[str, bool]]:
        return self.confirmation.queue

    @property
    def state(self) -> RunState:
        """Return the mutable lifecycle state owned by this runtime."""
        return self._state

    @property
    def phase(self) -> RunPhase:
        return self._state.phase

    @property
    def active_run_id(self) -> str | None:
        """Return the run id only while the runtime is active."""
        if self._state.phase is RunPhase.IDLE:
            return None
        return self._state.run_id

    @property
    def side_effect_state(self) -> str:
        return self._side_effects.state

    @property
    def cleanup_uncertain(self) -> bool:
        return self._side_effects.cleanup_uncertain

    @property
    def cleanup_status(self) -> str:
        return self._side_effects.cleanup_status

    def set_event_handler(self, handler: Callable[[AgentEvent, str], None]) -> None:
        self._event_handler = handler

    async def wait_for_idle(self, timeout: float | None = None) -> bool:
        """Wait until the current run has completed its session cleanup."""
        if self.phase is RunPhase.IDLE:
            return True
        task = self.current_task
        if task is None or task is asyncio.current_task():
            return self.phase is RunPhase.IDLE
        try:
            waiter = asyncio.shield(task)
            if timeout is None:
                await waiter
            else:
                await asyncio.wait_for(waiter, timeout)
        except BaseException:
            # The run owns its terminal event and cleanup in a finally block;
            # waiting observes that boundary without re-raising its outcome.
            pass
        return self.phase is RunPhase.IDLE

    async def cancel_and_wait(self, timeout: float | None = None) -> bool:
        """Request cancellation and wait for the run to become idle."""
        self.abort()
        return await self.wait_for_idle(timeout)

    def start_run(self) -> str:
        if self._state.phase is not RunPhase.IDLE or self.current_task is not None:
            raise RuntimeError("run already active")
        run_id = str(uuid.uuid4())
        self._state = RunState(
            run_id=run_id,
            session_id=self._session_id,
            phase=RunPhase.STARTING,
        )
        self._side_effects.reset()
        self.last_failure = None
        self.last_outcome = None
        self.turn_usage = UsageStats()
        return run_id

    def _agent_steer(self, text: str) -> None:
        if self.phase is RunPhase.FINALIZING:
            # The model execution boundary is closed. A late steer belongs to
            # neither the committed turn nor the next independent run.
            return
        if self.agent is not None and self.agent.is_running:
            self.agent.steer(text)
        else:
            self.inject_queue.put_nowait(text)

    def set_failure(self, failure: RuntimeFailure) -> None:
        self._state.failure = failure
        if self._state.phase not in {RunPhase.FAILED, RunPhase.FINALIZING}:
            self._state.transition(RunPhase.FAILED)

    def begin_finalization(self) -> None:
        """Close the execution-input window before session-owned commit work."""
        if self._state.phase in {
            RunPhase.IDLE,
            RunPhase.COMPLETED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.FINALIZING,
        }:
            return
        self._state.transition(RunPhase.FINALIZING)

    def finish_run(
        self,
        outcome: RunPhase | RunOutcome | None = None,
    ) -> RunOutcome:
        """Move the active run through its terminal phase and back to idle.

        ``RunOutcome`` is retained after the runtime returns to idle so
        callers can inspect the commit boundary without racing the terminal
        event.  The old ``RunPhase`` argument remains accepted for low-level
        callers and tests.
        """
        if self._state.phase is RunPhase.IDLE:
            self.current_task = None
            self.agent = None
            self.confirmation.clear()
            self._clear_injected_messages()
            if self.last_outcome is not None:
                return self.last_outcome
            run_id = self._state.run_id or ""
            self.last_outcome = RunOutcome(
                run_id=run_id,
                phase=RunPhase.COMPLETED,
                commit_status=CommitStatus.NOT_ATTEMPTED,
            )
            return self.last_outcome
        if isinstance(outcome, RunOutcome):
            resolved = outcome
            target = outcome.phase
        else:
            target = outcome
            resolved = RunOutcome(
                run_id=self._state.run_id or "",
                phase=target or self._state.phase,
            )
        if target is not None and self._state.phase is not target:
            self._state.transition(target)
        if self._state.phase is not RunPhase.FINALIZING:
            self._state.transition(RunPhase.FINALIZING)
        self._state.transition(RunPhase.IDLE)
        self.last_outcome = resolved
        self.current_task = None
        self.agent = None
        self.confirmation.clear()
        self._clear_injected_messages()
        return resolved

    def _clear_injected_messages(self) -> None:
        while not self.inject_queue.empty():
            self.inject_queue.get_nowait()

    def record_usage(self, payload: dict[str, Any]) -> None:
        self.turn_usage = UsageStats(
            input_tokens=self.turn_usage.input_tokens
            + int(payload.get("input_tokens", 0) or 0),
            output_tokens=self.turn_usage.output_tokens
            + int(payload.get("output_tokens", 0) or 0),
            reasoning_tokens=self.turn_usage.reasoning_tokens
            + int(payload.get("reasoning_tokens", 0) or 0),
            cached_tokens=self.turn_usage.cached_tokens
            + int(payload.get("cached_tokens", 0) or 0),
        )

    def abort(self) -> bool:
        active = self.phase is not RunPhase.IDLE or self.current_task is not None
        if not active:
            return False
        task = self.current_task
        if not self._state.cancellation_requested:
            self._state.cancellation_requested = True
            self._emit(
                AgentEvent(
                    EventType.CANCELLING,
                    metadata={
                        "side_effect_state": self.side_effect_state,
                        "cleanup_uncertain": self.cleanup_uncertain,
                        "cleanup_status": self.cleanup_status,
                    },
                ),
                self.active_run_id,
            )
            self.confirmation.cancel_all()
        if task is not None and not task.done():
            task.cancel()
        return True

    def inject(self, text: str) -> None:
        self._agent_steer(text)

    def respond_approval(self, request_id: str, approved: bool) -> None:
        accepted = self.confirmation.respond(request_id, approved)
        if not accepted and not self.confirmation.active_request_ids:
            # Legacy observers may inspect the response queue, but no runtime
            # waiter consumes it and a future registration drains it first.
            self.confirmation.queue.put_nowait((request_id, approved))
