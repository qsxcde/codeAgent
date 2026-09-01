"""Serial application-layer runner for temporary Subagent sessions."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from codeagent.core.contracts.events import AgentEvent
from codeagent.core.contracts.subagents import (
    SubagentFailurePhase,
    SubagentReasonCode,
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
)

from .runner_support import (
    cancel_session,
    cancelled_result,
    child_outcome,
    child_run_id,
    child_summary,
    close_active,
    diagnostic,
    failure_result,
    observe_event,
    rejected_result,
)

ChildSessionFactory = Callable[[SubagentRequest], Any]


@dataclass
class _ActiveDelegation:
    request: SubagentRequest
    attempt_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session: Any = None
    task: asyncio.Task[Any] | None = None
    child_run_id: str | None = None
    cancel_requested: bool = False
    unsubscribe: Callable[[], None] | None = None
    event_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    diagnostics: list[str] = field(default_factory=list)


class SerialSubagentRunner:
    """Run at most one isolated child Session at a time."""

    def __init__(self, child_session_factory: ChildSessionFactory) -> None:
        if not callable(child_session_factory):
            raise TypeError("child_session_factory must be callable")
        self._child_session_factory = child_session_factory
        self._lock = asyncio.Lock()
        self._active: dict[str, _ActiveDelegation] = {}

    @property
    def active_delegations(self) -> dict[str, str | None]:
        """Return a read-only diagnostic snapshot of active child identities."""
        return {
            delegation_id: getattr(active.session, "session_id", None)
            for delegation_id, active in self._active.items()
        }

    async def execute(
        self,
        request: SubagentRequest,
        *,
        on_event: Callable[[AgentEvent], Any] | None = None,
    ) -> SubagentResult:
        rejection = self._validate_request(request)
        if rejection is not None:
            return rejection

        active = _ActiveDelegation(request)
        self._active[request.delegation_id] = active
        try:
            async with self._lock:
                if active.cancel_requested:
                    return cancelled_result(active)
                try:
                    child = self._child_session_factory(request)
                    if inspect.isawaitable(child):
                        child = await child
                except Exception as exc:  # noqa: BLE001 - startup is normalized
                    return failure_result(
                        active,
                        SubagentStatus.FAILED,
                        SubagentReasonCode.STARTUP_FAILED,
                        SubagentFailurePhase.STARTING,
                        exc,
                    )
                active.session = child
                active.unsubscribe = self._subscribe_child(active, on_event)
                active.task = asyncio.create_task(
                    child.run(request.task),
                    name=f"subagent:{request.delegation_id}",
                )
                await asyncio.sleep(0)
                active.child_run_id = child_run_id(child) or active.child_run_id
                try:
                    returned = await active.task
                except asyncio.CancelledError:
                    if active.cancel_requested:
                        return cancelled_result(active)
                    raise
                except Exception as exc:  # noqa: BLE001 - child is isolated
                    return failure_result(
                        active,
                        SubagentStatus.FAILED,
                        SubagentReasonCode.EXECUTION_FAILED,
                        SubagentFailurePhase.RUNNING,
                        exc,
                    )
                active.child_run_id = active.child_run_id or child_run_id(child)
                outcome_phase, outcome_error = child_outcome(child)
                if outcome_phase == "cancelled":
                    return cancelled_result(active)
                if outcome_phase == "failed":
                    return failure_result(
                        active,
                        SubagentStatus.FAILED,
                        SubagentReasonCode.EXECUTION_FAILED,
                        SubagentFailurePhase.RUNNING,
                        RuntimeError(outcome_error or "子 Agent 运行失败"),
                    )
                summary = child_summary(child, returned)
                return SubagentResult(
                    delegation_id=request.delegation_id,
                    status=SubagentStatus.COMPLETED,
                    child_run_id=active.child_run_id,
                    attempt_id=active.attempt_id,
                    summary=summary,
                    diagnostics=tuple(active.diagnostics),
                )
        except asyncio.CancelledError:
            active.cancel_requested = True
            await cancel_session(active)
            raise
        finally:
            await close_active(active)
            self._active.pop(request.delegation_id, None)

    async def cancel(self, delegation_id: str) -> bool:
        active = self._active.get(delegation_id)
        if active is None:
            return False
        active.cancel_requested = True
        await cancel_session(active)
        return True

    def _subscribe_child(
        self,
        active: _ActiveDelegation,
        on_event: Callable[[AgentEvent], Any] | None,
    ) -> Callable[[], None] | None:
        subscribe = getattr(active.session, "subscribe", None)
        if not callable(subscribe):
            return None

        def handle(event: AgentEvent) -> None:
            event_child_run_id = getattr(event, "run_id", None) or child_run_id(active.session)
            if event_child_run_id:
                active.child_run_id = event_child_run_id
            if on_event is None:
                return
            metadata = dict(getattr(event, "metadata", {}) or {})
            metadata.update(
                {
                    "delegation_id": active.request.delegation_id,
                    "parent_run_id": active.request.parent_run_id,
                    "child_run_id": event_child_run_id,
                    "attempt_id": active.attempt_id,
                    "depth": active.request.depth,
                }
            )
            enriched = replace(
                event,
                metadata=metadata,
                delegation_id=active.request.delegation_id,
                parent_run_id=active.request.parent_run_id,
                child_run_id=event_child_run_id,
                attempt_id=active.attempt_id,
                depth=active.request.depth,
            )
            try:
                result = on_event(enriched)
            except Exception as exc:  # noqa: BLE001 - observers are isolated
                active.diagnostics.append(diagnostic("子事件回调", exc))
            else:
                if inspect.isawaitable(result):
                    task = asyncio.create_task(observe_event(result, active))
                    active.event_tasks.add(task)
                    task.add_done_callback(active.event_tasks.discard)

        return subscribe(handle)

    def _validate_request(self, request: Any) -> SubagentResult | None:
        if not isinstance(request, SubagentRequest):
            return rejected_result(
                request,
                SubagentReasonCode.INVALID_REQUEST.value,
                "委派请求类型无效",
            )
        if request.profile != "read_only":
            return rejected_result(
                request,
                SubagentReasonCode.PERMISSION_DENIED.value,
                "当前 runner 只接受 read_only profile",
            )
        if request.depth > request.max_depth or request.depth > 1:
            return rejected_result(
                request,
                SubagentReasonCode.DEPTH_EXCEEDED.value,
                "子 Agent 深度超过当前 MVP 限制",
            )
        if request.delegation_id in self._active:
            return rejected_result(
                request,
                SubagentReasonCode.INVALID_REQUEST.value,
                "委派标识已经处于活动状态",
            )
        return None
__all__ = ["ChildSessionFactory", "SerialSubagentRunner"]
