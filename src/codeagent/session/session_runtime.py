"""Runtime coordination for AgentSession turns and run control."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from codeagent.core.events import AgentEvent, EventType
from codeagent.core.loop import run_turn
from codeagent.core.messages import Message
from codeagent.core.ports import AgentPorts
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
        ports: AgentPorts,
        text: str,
        *,
        history: list[Message],
        recursion_limit: int,
        tool_timeout: float | None,
    ) -> list[Message]:
        if self.active_run_id is None:
            raise RuntimeError("run must be started before execution")
        run_id = self.active_run_id
        self.current_task = asyncio.current_task()
        try:
            return await run_turn(
                ports,
                lambda event: self._handle_event(event, run_id),
                text,
                history=history,
                recursion_limit=recursion_limit,
                inject_queue=self.inject_queue,
                tool_timeout=tool_timeout,
                confirm_queue=self.confirm_queue,
            )
        finally:
            self.current_task = None

    def _handle_event(self, event: AgentEvent, run_id: str) -> None:
        self.observe_event(event)
        if self._event_handler is not None:
            self._event_handler(event, run_id)

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
        self.inject_queue.put_nowait(text)

    def respond_approval(self, request_id: str, approved: bool) -> None:
        self.confirm_queue.put_nowait((request_id, approved))

    def finish_run(self) -> None:
        self.active_run_id = None
