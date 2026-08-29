"""Lifecycle controller for one session run."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import fields, replace
from typing import Any, Callable

from codeagent.core import Agent, AgentContext, ToolDecision
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.session.persistence.models import UsageStats
from codeagent.session.runtime.confirmation import ConfirmationCoordinator
from codeagent.session.runtime.event_mapper import EventMapper, SideEffectObserver
from codeagent.session.runtime.state import (
    CommitStatus,
    RunOutcome,
    RunPhase,
    RunState,
    RuntimeFailure,
)

AgentFactory = Callable[[AgentContext, AgentLoopConfig, int], Agent]


def _default_agent_factory(
    context: AgentContext, config: AgentLoopConfig, recursion_limit: int
) -> Agent:
    return Agent(context, config, recursion_limit=recursion_limit)


class SessionRuntime:
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

    async def execute(
        self,
        config: AgentLoopConfig,
        text: str,
        *,
        history: list[Message],
        recursion_limit: int,
        tool_timeout: float | None,
        policy: Any = None,
        transform_context: Callable[[list[Message]], Any] | None = None,
    ) -> list[Message]:
        if self.active_run_id is None:
            raise RuntimeError("run must be started before execution")
        run_id = self.active_run_id
        self.current_task = asyncio.current_task()
        try:
            context = AgentContext(messages=list(history), tools=list(config.tools))

            async def before_tool_call(call, _context):
                if policy is None:
                    return ToolDecision.allow()
                decision = policy.decide(call.name, call.args)
                if decision.action == "allow":
                    return ToolDecision.allow()
                if decision.action == "deny":
                    return ToolDecision.block(decision.reason)
                request_id = str(uuid.uuid4())
                self.confirmation.register(
                    request_id, timeout=self._confirmation_timeout
                )
                self._handle_event(
                    AgentEvent(
                        EventType.CONFIRMATION_REQUESTED,
                        payload={
                            "request_id": request_id,
                            "tool": call.name,
                            "args": call.args,
                            "reason": decision.reason,
                        },
                    ),
                    run_id,
                )
                approved = await self.confirmation.wait(
                    request_id, timeout=self._confirmation_timeout
                )
                return (
                    ToolDecision.allow()
                    if approved
                    else ToolDecision.block("用户拒绝执行")
                )

            pending_steer: list[str] = []
            while not self.inject_queue.empty():
                pending_steer.append(self.inject_queue.get_nowait())
            # ``config`` may be the composition root's lazy proxy rather than
            # the dataclass itself. Copy declared fields dynamically so lazy
            # configuration and newly added AgentLoopConfig fields follow the
            # same path without silently dropping execution options.
            config_values = {
                item.name: getattr(config, item.name)
                for item in fields(AgentLoopConfig)
            }
            config_values.update(
                {
                    "tools": list(config_values["tools"]),
                    "before_tool_call": before_tool_call,
                    "tool_timeout": tool_timeout,
                    # A session-level transform overrides the config-level
                    # hook; otherwise preserve the hook already assembled in
                    # AgentLoopConfig so the runtime path matches core.
                    "transform_context": transform_context
                    or config_values["transform_context"],
                }
            )
            agent_config = AgentLoopConfig(**config_values)
            self.agent = self._agent_factory(
                context,
                agent_config,
                recursion_limit,
            )
            set_run_id = getattr(self.agent, "set_run_id", None)
            if callable(set_run_id):
                set_run_id(run_id)
            for steer in pending_steer:
                self.agent.steer(steer)
            self.agent.subscribe(lambda event: self._handle_event(event, run_id))
            return await self.agent.prompt(text)
        finally:
            # The session owns post-execution commit and compaction as part
            # of the same run. Keep the task reference until finish_run so
            # abort()/wait_for_idle() also cover that finalization window.
            pass

    def _agent_steer(self, text: str) -> None:
        if self.phase is RunPhase.FINALIZING:
            # The model execution boundary is closed. A late steer belongs to
            # neither the committed turn nor the next independent run.
            return
        if self.agent is not None and self.agent.is_running:
            self.agent.steer(text)
        else:
            self.inject_queue.put_nowait(text)

    def _handle_event(self, event: AgentEvent, run_id: str) -> None:
        if self._state.phase is RunPhase.IDLE or self._state.run_id != run_id:
            return
        for item in EventMapper.map_agent_event(event):
            if item.run_id is not None and item.run_id != run_id:
                continue
            metadata = dict(item.metadata or {})
            metadata.setdefault("run_id", run_id)
            item = replace(item, metadata=metadata, run_id=item.run_id or run_id)
            self.observe_event(item)
            metadata = dict(item.metadata or {})
            metadata.setdefault("phase", self.phase.value)
            metadata["sequence"] = self._state.next_sequence()
            item = replace(item, metadata=metadata, phase=self.phase.value)
            # The core error/aborted notification is an internal process event.
            # Session emits the single structured terminal event in AgentSession.
            if item.type in {EventType.ERROR, EventType.ABORTED}:
                continue
            if self._event_handler is not None:
                self._event_handler(item, run_id)

    @staticmethod
    def _map_agent_event(event: AgentEvent) -> list[AgentEvent]:
        return EventMapper.map_agent_event(event)

    def observe_event(self, event: AgentEvent) -> None:
        self._side_effects.observe(event)
        self._advance_phase(event)

    def _advance_phase(self, event: AgentEvent) -> None:
        """Advance lifecycle state from observable core/session events."""
        target: RunPhase | None = None
        if event.type == EventType.MESSAGE_START:
            target = RunPhase.MODEL_WAIT
        elif event.type in {EventType.TOOL_EXECUTION_START, EventType.TOOL_STARTED}:
            target = RunPhase.TOOL_RUNNING
        elif event.type == EventType.CONFIRMATION_REQUESTED:
            target = RunPhase.AWAITING_CONFIRMATION
        elif event.type == EventType.ERROR:
            target = RunPhase.FAILED
        elif event.type == EventType.ABORTED:
            target = RunPhase.CANCELLED
        elif event.type == EventType.TURN_END and (event.metadata or {}).get("tool_results"):
            target = RunPhase.CONTINUING
        if target is None or self._state.phase is RunPhase.IDLE:
            return
        try:
            self._state.transition(target)
        except ValueError:
            # A late event from an already terminal operation must not corrupt
            # the current run state. The event is still available to the
            # caller when it is not a stale run id.
            if self._state.phase in {
                RunPhase.COMPLETED,
                RunPhase.FAILED,
                RunPhase.CANCELLED,
                RunPhase.FINALIZING,
            }:
                return
            raise

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
