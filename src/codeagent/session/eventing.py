"""Event correlation helpers for the session facade."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from typing import Any

from codeagent.core.contracts.events import AgentEvent
from codeagent.core.contracts.hooks import (
    HookDiagnostic,
    HookFailureStage,
    HookPhase,
    HookScope,
    LifecycleHook,
    LifecycleHookEvent,
    classify_session_event,
    make_hook_diagnostic,
    session_event_phase,
)


class SessionEventMixin:
    """Add session/run correlation before publishing an event."""

    def _on_run_event(self, event: AgentEvent, run_id: str) -> None:
        self._emit(event, run_id)

    def _emit(self, event: AgentEvent, run_id: str | None) -> None:
        metadata = dict(event.metadata or {})
        metadata.setdefault("session_id", self._session_id)
        if run_id is not None:
            metadata.setdefault("run_id", run_id)
            if "sequence" not in metadata:
                metadata["sequence"] = self._runtime.state.next_sequence()
        normalized = replace(
            event,
            metadata=metadata,
            session_id=event.session_id or self._session_id,
            run_id=event.run_id or run_id,
            tool_call_id=event.tool_call_id or metadata.get("tool_call_id"),
            operation_id=event.operation_id or metadata.get("operation_id"),
            phase=event.phase or metadata.get("phase"),
            elapsed_ms=event.elapsed_ms or metadata.get("elapsed_ms"),
            error_code=event.error_code or metadata.get("error_code"),
            retryable=(
                event.retryable
                if event.retryable is not None
                else metadata.get("retryable")
            ),
            cleanup_uncertain=(
                event.cleanup_uncertain
                if event.cleanup_uncertain is not None
                else metadata.get("cleanup_uncertain")
            ),
            cleanup_status=event.cleanup_status or metadata.get("cleanup_status"),
            side_effect_state=event.side_effect_state or metadata.get("side_effect_state"),
            status=event.status or metadata.get("status"),
            tool_name=event.tool_name or metadata.get("tool_name"),
            queue_position=(
                event.queue_position
                if event.queue_position is not None
                else metadata.get("queue_position")
            ),
        )
        self._notify_lifecycle_hooks(normalized)
        self._bus.emit(normalized)

    def _notify_lifecycle_hooks(self, event: AgentEvent) -> None:
        try:
            lifecycle = classify_session_event(event)
        except Exception as exc:  # noqa: BLE001 - observer snapshot is isolated
            self._record_lifecycle_hook_failure(
                event,
                exc,
                stage="snapshot",
                scope="session",
                phase=session_event_phase(event),
            )
            return
        hooks = self._lifecycle_hooks
        if hooks is None:
            hooks = tuple(getattr(self._config, "lifecycle_hooks", ()))
        for hook in hooks:
            try:
                result = hook(lifecycle)
            except Exception as exc:  # noqa: BLE001 - isolated observer
                self._record_lifecycle_hook_failure(
                    event,
                    exc,
                    stage="invoke",
                    hook=hook,
                    lifecycle=lifecycle,
                )
                continue
            if inspect.isawaitable(result):
                task = asyncio.ensure_future(result)
                self._lifecycle_hook_tasks.add(task)
                task.add_done_callback(
                    lambda completed: self._finish_lifecycle_hook(
                        completed, event, lifecycle, hook
                    )
                )

    def _finish_lifecycle_hook(
        self,
        task: asyncio.Future[Any],
        event: AgentEvent,
        lifecycle: LifecycleHookEvent,
        hook: LifecycleHook,
    ) -> None:
        self._lifecycle_hook_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._record_lifecycle_hook_failure(
                event,
                exception,
                stage="await",
                hook=hook,
                lifecycle=lifecycle,
            )

    def _record_lifecycle_hook_failure(
        self,
        event: AgentEvent,
        exception: Exception,
        *,
        stage: HookFailureStage,
        hook: LifecycleHook | None = None,
        lifecycle: LifecycleHookEvent | None = None,
        scope: HookScope | None = None,
        phase: HookPhase | None = None,
    ) -> None:
        self._lifecycle_hook_diagnostics.append(
            make_hook_diagnostic(
                event,
                exception,
                stage=stage,
                hook=hook,
                scope=lifecycle.scope if lifecycle is not None else scope,
                phase=lifecycle.phase if lifecycle is not None else phase,
            )
        )
        # Keep the V4-28 compatibility surface populated as well.
        self._lifecycle_hook_errors.append((event, exception))

    async def _drain_lifecycle_hooks(self) -> None:
        tasks = tuple(self._lifecycle_hook_tasks)
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            for task in tasks:
                if not task.done():
                    task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["SessionEventMixin"]
