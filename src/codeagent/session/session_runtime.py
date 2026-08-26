"""Runtime coordination for AgentSession turns and run control."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from codeagent.core.events import AgentEvent, EventType
from codeagent.core import Agent, AgentContext, AgentTool, ToolDecision
from codeagent.core.messages import Message
from codeagent.core.ports import AgentLoopConfig
from codeagent.session.store_models import UsageStats


class SessionRuntime:
    """Own mutable state associated with one active AgentSession run."""

    def __init__(
        self,
        emit: Callable[[AgentEvent, str | None], None],
        event_handler: Callable[[AgentEvent, str], None] | None = None,
    ) -> None:
        self._emit = emit
        self._event_handler = event_handler
        self.inject_queue: asyncio.Queue[str] = asyncio.Queue()
        self.confirm_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        self.current_task: asyncio.Task[None] | None = None
        self.active_run_id: str | None = None
        self.side_effect_state = "none"
        self.cleanup_uncertain = False
        self.last_failure: dict[str, Any] | None = None
        self.turn_usage = UsageStats()
        self.agent: Agent | None = None

    def set_event_handler(
        self, handler: Callable[[AgentEvent, str], None]
    ) -> None:
        self._event_handler = handler

    def start_run(self) -> str:
        self.active_run_id = str(uuid.uuid4())
        self.side_effect_state = "none"
        self.cleanup_uncertain = False
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
            selected_policy = policy

            async def before_tool_call(call, _context):
                if selected_policy is None:
                    return ToolDecision.allow()
                decision = selected_policy.decide(call.name, call.args)
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
                approved = await self._await_confirmation(request_id)
                return (
                    ToolDecision.allow()
                    if approved
                    else ToolDecision.block("用户拒绝执行")
                )

            pending_steer: list[str] = []
            while not self.inject_queue.empty():
                pending_steer.append(self.inject_queue.get_nowait())
            self.agent = Agent(
                context,
                AgentLoopConfig(
                    model=config.model,
                    tools=list(config.tools),
                    before_tool_call=before_tool_call,
                    tool_runtime=config.tool_runtime,
                    tool_timeout=tool_timeout,
                    transform_context=transform_context or (lambda messages: list(messages)),
                ),
                recursion_limit=recursion_limit,
            )
            for steer in pending_steer:
                self.agent.steer(steer)
            self.agent.subscribe(lambda event: self._handle_event(event, run_id))
            return await self.agent.prompt(text)
        finally:
            self.current_task = None

    async def _await_confirmation(self, request_id: str) -> bool:
        while True:
            got_id, approved = await self.confirm_queue.get()
            if got_id == request_id:
                return approved

    def _agent_steer(self, text: str) -> None:
        if self.agent is not None and self.agent.is_running:
            self.agent.steer(text)
        else:
            self.inject_queue.put_nowait(text)

    def _handle_event(self, event: AgentEvent, run_id: str) -> None:
        mapped = self._map_agent_event(event)
        for item in mapped:
            self.observe_event(item)
            if self._event_handler is not None:
                self._event_handler(item, run_id)

    @staticmethod
    def _map_agent_event(event: AgentEvent) -> list[AgentEvent]:
        """Translate core Agent lifecycle events to existing Session events."""
        if event.type == EventType.MESSAGE_UPDATE:
            if isinstance(event.payload, dict):
                kind = event.payload.get("type")
                if kind == "thinking_delta":
                    return [AgentEvent(EventType.THINKING_DELTA, event.payload.get("text", {}))]
                if kind in {"tool_call", "tool_call_delta"}:
                    return [
                        AgentEvent(
                            EventType.TOOL_CALL,
                            payload=[
                                {
                                    "id": event.payload.get("tool_call_id"),
                                    "name": event.payload.get("tool_name", ""),
                                    "args": event.payload.get("arguments", {}),
                                }
                            ],
                        )
                    ]
            return [AgentEvent(EventType.TEXT_DELTA, event.payload)]
        if event.type == EventType.MESSAGE_END:
            message = event.payload
            if getattr(message, "content", ""):
                return []
            return [AgentEvent(EventType.AGENT_MESSAGE, "")]
        if event.type == EventType.TOOL_EXECUTION_START:
            payload = event.payload or {}
            return [
                AgentEvent(
                    EventType.TOOL_STARTED,
                    payload=payload,
                    metadata={
                        "tool_call_id": payload.get("tool_call_id"),
                        "tool_name": payload.get("tool_name"),
                    },
                )
            ]
        if event.type == EventType.TOOL_EXECUTION_UPDATE:
            return [AgentEvent(EventType.TOOL_PROGRESS, event.payload, event.metadata)]
        if event.type == EventType.TOOL_EXECUTION_END:
            result = event.payload
            metadata = dict(event.metadata or {})
            metadata.update(
                {
                    "tool_call_id": getattr(result, "tool_call_id", None),
                    "status": getattr(result, "status", None),
                    "error": getattr(result, "error", False),
                    "cleanup_uncertain": getattr(result, "cleanup_confirmed", True) is False,
                }
            )
            return [
                AgentEvent(EventType.TOOL_FINISHED, getattr(result, "content", result), metadata=metadata),
                AgentEvent(EventType.TOOL_RESULT, getattr(result, "content", result), metadata=metadata),
            ]
        return [event]

    def observe_event(self, event: AgentEvent) -> None:
        if event.type == EventType.TOOL_STARTED:
            self.side_effect_state = "possible"
        elif event.type == EventType.TOOL_FINISHED:
            metadata = dict(event.metadata or {})
            if metadata.get("cleanup_uncertain"):
                self.cleanup_uncertain = True
                self.side_effect_state = "uncertain"
            elif metadata.get("status") not in {None, "ok", "rejected"}:
                self.side_effect_state = "possible"

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
        self.confirm_queue.put_nowait((request_id, approved))

    def finish_run(self) -> None:
        self.active_run_id = None
        self.agent = None
