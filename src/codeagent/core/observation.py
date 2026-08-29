"""Lifecycle observation support for the provider-neutral core Agent."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from codeagent.core.contracts.events import AgentEvent
from codeagent.core.contracts.hooks import (
    HookDiagnostic,
    HookFailureStage,
    LifecycleHook,
    LifecycleHookEvent,
    classify_core_event,
    core_event_scope_phase,
    make_hook_diagnostic,
)


class LifecycleHookObservationMixin:
    """Dispatch core lifecycle Hooks without coupling them to Agent control."""

    @property
    def hook_diagnostics(self) -> list[HookDiagnostic]:
        """Return structured Hook failures collected during this Agent's runs."""
        return list(self._hook_diagnostics)

    def _notify_lifecycle_hooks(self, event: AgentEvent) -> None:
        try:
            lifecycle = classify_core_event(event)
        except Exception as exc:  # noqa: BLE001 - observer snapshot is isolated
            lifecycle_mapping = core_event_scope_phase(event.type)
            scope, phase = lifecycle_mapping or (None, None)
            self._record_hook_failure(event, exc, stage="snapshot", scope=scope, phase=phase)
            return
        if lifecycle is None:
            return
        for hook in self._lifecycle_hooks:
            try:
                result = hook(lifecycle)
            except Exception as exc:  # noqa: BLE001 - observers are isolated
                self._record_hook_failure(
                    event,
                    exc,
                    stage="invoke",
                    hook=hook,
                    lifecycle=lifecycle,
                )
                continue
            if inspect.isawaitable(result):
                task = asyncio.ensure_future(result)
                self._listener_tasks.add(task)
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
        self._listener_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._record_hook_failure(
                event,
                exception,
                stage="await",
                hook=hook,
                lifecycle=lifecycle,
            )

    def _record_hook_failure(
        self,
        event: AgentEvent,
        exception: Exception,
        *,
        stage: HookFailureStage,
        hook: LifecycleHook | None = None,
        lifecycle: LifecycleHookEvent | None = None,
        scope: str | None = None,
        phase: str | None = None,
    ) -> None:
        self._hook_diagnostics.append(
            make_hook_diagnostic(
                event,
                exception,
                stage=stage,
                hook=hook,
                scope=lifecycle.scope if lifecycle is not None else scope,
                phase=lifecycle.phase if lifecycle is not None else phase,
            )
        )
        # Keep the pre-existing compatibility surface populated as well.
        self._listener_errors.append((event, exception))


__all__ = ["LifecycleHookObservationMixin"]
