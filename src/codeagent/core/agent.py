"""Stateful in-memory facade for the low-level Agent Runtime loop."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from codeagent.core.context import AgentContext
from codeagent.core.errors import AgentRuntimeError
from codeagent.core.events import AgentEvent
from codeagent.core.execution import ToolExecutionRuntime
from codeagent.core.loop import (
    DEFAULT_RECURSION_LIMIT,
    run_agent_loop,
    run_agent_loop_continue,
)
from codeagent.core.messages import Message
from codeagent.core.ports import AgentLoopConfig

EventListener = Callable[[AgentEvent], Any]


class Agent:
    """Own mutable runtime context without persistence or application policy.

    The loop works on a copy of the context.  A completed run is committed to
    this object only after the loop returns successfully, which gives session
    layers a simple rollback boundary.
    """

    def __init__(
        self,
        context: AgentContext,
        config: AgentLoopConfig,
        *,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        run_id: str | None = None,
    ) -> None:
        self._context = context
        self._steer_messages: list[str] = []
        self._config = replace(
            config,
            steer_queue=self._steer_messages,
            tool_runtime=config.tool_runtime or ToolExecutionRuntime(),
        )
        self._recursion_limit = recursion_limit
        self._run_id = run_id
        self._listeners: list[EventListener] = []
        self._listener_errors: list[tuple[AgentEvent, Exception]] = []
        self._task: asyncio.Task[list[Message]] | None = None
        self._follow_ups: list[tuple[str, asyncio.Future[list[Message]]]] = []

    @property
    def context(self) -> AgentContext:
        """Return the live in-memory context owned by this Agent."""
        return self._context

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def set_run_id(self, run_id: str | None) -> None:
        """Attach the correlation id used by all subsequent core events."""
        self._run_id = run_id

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Subscribe to Agent events and return an idempotent unsubscribe."""
        self._listeners.append(listener)
        removed = False

        def unsubscribe() -> None:
            nonlocal removed
            if not removed:
                removed = True
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass

        return unsubscribe

    @property
    def listener_errors(self) -> list[tuple[AgentEvent, Exception]]:
        """Return listener failures without making them runtime failures."""
        return list(self._listener_errors)

    def _emit(self, event: AgentEvent) -> None:
        if self._run_id is not None:
            metadata = dict(event.metadata or {})
            metadata.setdefault("run_id", self._run_id)
            event = replace(
                event,
                metadata=metadata,
                run_id=event.run_id or self._run_id,
            )
        for listener in tuple(self._listeners):
            try:
                result = listener(event)
            except Exception as exc:  # noqa: BLE001 - observers are isolated
                self._listener_errors.append((event, exc))
                continue
            if inspect.isawaitable(result):
                asyncio.create_task(self._consume_listener(result, event))

    async def _consume_listener(self, result: Any, event: AgentEvent) -> None:
        try:
            await result
        except Exception as exc:  # noqa: BLE001 - observers are isolated
            self._listener_errors.append((event, exc))

    async def _execute(self, prompt: str | None, *, continue_: bool) -> list[Message]:
        if self.is_running:
            raise AgentRuntimeError("agent is already running")

        async def run_once(
            run_prompt: str | None, run_continue: bool
        ) -> list[Message]:
            if run_continue:
                return await run_agent_loop_continue(
                    self._context,
                    self._config,
                    emit=self._emit,
                    recursion_limit=self._recursion_limit,
                )
            assert run_prompt is not None
            return await run_agent_loop(
                self._context,
                self._config,
                run_prompt,
                emit=self._emit,
                recursion_limit=self._recursion_limit,
            )

        task = asyncio.current_task()
        assert task is not None
        self._task = task
        all_messages: list[Message] = []
        try:
            messages = await run_once(prompt, continue_)
            self._steer_messages.clear()
            self._context.messages.extend(messages)
            all_messages.extend(messages)
            while self._follow_ups:
                follow_up, waiter = self._follow_ups.pop(0)
                try:
                    messages = await run_once(follow_up, False)
                    self._steer_messages.clear()
                    self._context.messages.extend(messages)
                    all_messages.extend(messages)
                except BaseException as exc:
                    if not waiter.done():
                        waiter.set_exception(exc)
                    raise
                else:
                    if not waiter.done():
                        waiter.set_result(messages)
        finally:
            if self._task is task:
                self._task = None
            # A cancelled run must not leak steering input into a later run.
            self._steer_messages.clear()
            if self._follow_ups:
                error = AgentRuntimeError("agent run did not complete")
                for _, waiter in self._follow_ups:
                    if not waiter.done():
                        waiter.set_exception(error)
                self._follow_ups.clear()
        return all_messages

    async def prompt(self, text: str) -> list[Message]:
        """Append a user prompt and run the Agent until it reaches a turn end."""
        return await self._execute(text, continue_=False)

    async def continue_(self) -> list[Message]:
        """Continue from an existing user or tool-result message."""
        return await self._execute(None, continue_=True)

    def abort(self) -> bool:
        """Cancel the active run, returning whether a task was cancelled."""
        if not self.is_running or self._task is None:
            return False
        self._task.cancel()
        return True

    def steer(self, text: str) -> None:
        """Queue a steering message for the next model request.

        The low-level loop drains this queue after the current tool batch and
        persists the message in the completed run's new-message list.
        """
        self._steer_messages.append(text)

    async def follow_up(self, text: str) -> list[Message] | None:
        """Run a follow-up immediately when idle, or queue it while running."""
        if not self.is_running:
            return await self.prompt(text)
        waiter: asyncio.Future[list[Message]] = asyncio.get_running_loop().create_future()
        entry = (text, waiter)
        self._follow_ups.append(entry)
        try:
            return await waiter
        except asyncio.CancelledError:
            # Cancelling the caller must withdraw a queued follow-up before
            # the active run reaches its queue-draining boundary.
            try:
                self._follow_ups.remove(entry)
            except ValueError:
                pass
            if not waiter.done():
                waiter.cancel()
            raise


__all__ = ["Agent"]
