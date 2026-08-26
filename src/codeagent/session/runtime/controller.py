"""Lifecycle controller for one session run."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from codeagent.core import Agent, AgentContext, ToolDecision
from codeagent.core.events import AgentEvent, EventType
from codeagent.core.messages import Message
from codeagent.core.ports import AgentLoopConfig
from codeagent.session.persistence.models import UsageStats
from codeagent.session.runtime.confirmation import ConfirmationCoordinator
from codeagent.session.runtime.event_mapper import EventMapper, SideEffectObserver

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
    ) -> None:
        self._emit = emit
        self._event_handler = event_handler
        self._agent_factory = agent_factory or _default_agent_factory
        self.inject_queue: asyncio.Queue[str] = asyncio.Queue()
        self.confirmation = ConfirmationCoordinator()
        self.current_task: asyncio.Task[None] | None = None
        self.active_run_id: str | None = None
        self._side_effects = SideEffectObserver()
        self.last_failure: dict[str, Any] | None = None
        self.turn_usage = UsageStats()
        self.agent: Agent | None = None

    @property
    def agent_factory(self) -> AgentFactory:
        return self._agent_factory

    @property
    def confirm_queue(self) -> asyncio.Queue[tuple[str, bool]]:
        return self.confirmation.queue

    @property
    def side_effect_state(self) -> str:
        return self._side_effects.state

    @property
    def cleanup_uncertain(self) -> bool:
        return self._side_effects.cleanup_uncertain

    def set_event_handler(self, handler: Callable[[AgentEvent, str], None]) -> None:
        self._event_handler = handler

    def start_run(self) -> str:
        if self.active_run_id is not None:
            raise RuntimeError("run already active")
        self.active_run_id = str(uuid.uuid4())
        self._side_effects.reset()
        self.last_failure = None
        self.turn_usage = UsageStats()
        return self.active_run_id

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
                approved = await self.confirmation.wait(request_id)
                return (
                    ToolDecision.allow()
                    if approved
                    else ToolDecision.block("用户拒绝执行")
                )

            pending_steer: list[str] = []
            while not self.inject_queue.empty():
                pending_steer.append(self.inject_queue.get_nowait())
            self.agent = self._agent_factory(
                context,
                AgentLoopConfig(
                    model=config.model,
                    tools=list(config.tools),
                    before_tool_call=before_tool_call,
                    tool_runtime=config.tool_runtime,
                    tool_timeout=tool_timeout,
                    transform_context=transform_context
                    or (lambda messages: list(messages)),
                ),
                recursion_limit,
            )
            for steer in pending_steer:
                self.agent.steer(steer)
            self.agent.subscribe(lambda event: self._handle_event(event, run_id))
            return await self.agent.prompt(text)
        finally:
            self.current_task = None

    def _agent_steer(self, text: str) -> None:
        if self.agent is not None and self.agent.is_running:
            self.agent.steer(text)
        else:
            self.inject_queue.put_nowait(text)

    def _handle_event(self, event: AgentEvent, run_id: str) -> None:
        for item in EventMapper.map_agent_event(event):
            self.observe_event(item)
            if self._event_handler is not None:
                self._event_handler(item, run_id)

    @staticmethod
    def _map_agent_event(event: AgentEvent) -> list[AgentEvent]:
        return EventMapper.map_agent_event(event)

    def observe_event(self, event: AgentEvent) -> None:
        self._side_effects.observe(event)

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

    def abort(self) -> None:
        task = self.current_task
        if task is not None and not task.done():
            self._emit(
                AgentEvent(
                    EventType.CANCELLING,
                    metadata={
                        "side_effect_state": self.side_effect_state,
                        "cleanup_uncertain": self.cleanup_uncertain,
                    },
                ),
                self.active_run_id,
            )
            task.cancel()

    def inject(self, text: str) -> None:
        self._agent_steer(text)

    def respond_approval(self, request_id: str, approved: bool) -> None:
        self.confirmation.respond(request_id, approved)

    def finish_run(self) -> None:
        self.active_run_id = None
        self.agent = None
        self.confirmation.clear()
