"""Lifecycle and intervention methods for ``AgentSession``."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.ports import ApprovalPolicy
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.session.contracts import SessionCloser


class SessionLifecycleMixin:
    """Keep cancellation, shutdown and configuration changes together."""

    async def retry(self) -> None:
        failure = self._runtime.last_failure
        if not failure or not failure.get("retryable"):
            raise ValueError("当前失败不可安全重试,请确认副作用后使用 /continue")
        prompt = str(failure.get("prompt") or "")
        self._emit(
            AgentEvent(
                EventType.RETRY_STARTED,
                payload={"prompt": prompt},
                metadata={"operation": "retry", "previous_error": failure.get("error")},
            ),
            self._runtime.active_run_id,
        )
        await self.run(prompt)

    def abort(self) -> None:
        self._runtime.abort()

    async def wait_for_idle(self, timeout: float | None = None) -> bool:
        return await self._runtime.wait_for_idle(timeout)

    async def cancel_and_wait(self, timeout: float | None = None) -> bool:
        return await self._runtime.cancel_and_wait(timeout)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_resources())
        await asyncio.shield(self._close_task)

    async def _close_resources(self) -> None:
        await self.cancel_and_wait()
        if self._runtime_closer is not None:
            result = self._runtime_closer()
            if isinstance(result, Awaitable):
                await result

    def close_sync(self) -> asyncio.Task[None] | None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
            return None
        return asyncio.create_task(self.close())

    def steer(self, text: str) -> None:
        self._runtime.inject(text)

    def respond_approval(self, request_id: str, approved: bool) -> None:
        self._runtime.respond_approval(request_id, approved)

    def followup(self, text: str, recursion_limit: int | None = None) -> Awaitable[None]:
        return self.run(text, recursion_limit=recursion_limit)

    def replace_config(
        self,
        config: AgentLoopConfig,
        *,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        self._config = config
        if policy is not None:
            self._policy = policy
        model_window = getattr(getattr(config, "model", None), "context_window", None)
        if type(model_window) is int and model_window > 0:
            self._context_window = model_window
        self._budget_state.reset_for_model(self.model_id)

    def set_context_window(self, context_window: int) -> None:
        if type(context_window) is not int or context_window < 1:
            raise ValueError("context_window must be positive")
        self._context_window = context_window
        self._budget_state.reset_for_model(self.model_id)

    def run_sync(self, text: str) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.run(text))
            return

        result: list[BaseException | None] = [None]

        def _run() -> None:
            try:
                asyncio.run(self.run(text))
            except BaseException as exc:  # noqa: BLE001 - synchronous adapter rethrows
                result[0] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join()
        if result[0] is not None:
            raise result[0]


__all__ = ["SessionLifecycleMixin"]
