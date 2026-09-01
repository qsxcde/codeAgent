"""Child execution and budget observation for the serial Subagent runner."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.subagents import (
    SubagentFailurePhase,
    SubagentReasonCode,
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
)

from .active import ActiveDelegation
from .runner_support import (
    child_failure_code,
    child_outcome,
    child_run_id,
    child_summary,
    diagnostic,
    observe_event,
    record_diagnostic,
)
from .runner_results import (
    budget_exceeded_result,
    cancellation_result,
    failure_result,
)
from .context import render_subagent_prompt
from .result_extraction import extract_child_facts

ChildSessionFactory = Callable[[SubagentRequest], Any]


async def run_active(
    lock: asyncio.Lock,
    child_session_factory: ChildSessionFactory,
    active: ActiveDelegation,
    on_event: Callable[[AgentEvent], Any] | None,
) -> SubagentResult:
    """Start, observe and await one child while holding the serial slot."""
    async with lock:
        if active.cancel_requested:
            return cancellation_result(active)
        started = await _start_child(child_session_factory, active, on_event)
        if isinstance(started, SubagentResult):
            return started
        returned = await _await_child(active)
        if isinstance(returned, SubagentResult):
            return returned
        return _result_from_child(active, started, returned)


async def _start_child(
    child_session_factory: ChildSessionFactory,
    active: ActiveDelegation,
    on_event: Callable[[AgentEvent], Any] | None,
) -> Any | SubagentResult:
    try:
        child = child_session_factory(active.request)
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
    active.unsubscribe = subscribe_child(active, on_event)
    active.task = asyncio.create_task(
        child.run(
            render_subagent_prompt(
                active.request.task,
                active.request.profile,
                active.request.context,
            )
        ),
        name=f"subagent:{active.request.delegation_id}",
    )
    await asyncio.sleep(0)
    active.child_run_id = child_run_id(child) or active.child_run_id
    return child


async def _await_child(active: ActiveDelegation) -> Any | SubagentResult:
    try:
        returned = await asyncio.shield(active.task)
    except asyncio.CancelledError:
        if active.cancel_requested:
            return cancellation_result(active)
        raise
    except Exception as exc:  # noqa: BLE001 - child is isolated
        if active.cancel_reason is SubagentReasonCode.BUDGET_EXCEEDED:
            return budget_exceeded_result(active)
        return failure_result(
            active,
            SubagentStatus.FAILED,
            SubagentReasonCode.EXECUTION_FAILED,
            SubagentFailurePhase.RUNNING,
            exc,
        )
    return returned


def _result_from_child(
    active: ActiveDelegation,
    child: Any,
    returned: Any,
) -> SubagentResult:
    active.child_run_id = active.child_run_id or child_run_id(child)
    outcome_phase, outcome_error = child_outcome(child)
    if active.cancel_requested or outcome_phase == "cancelled":
        return cancellation_result(active)
    if outcome_phase == "failed":
        if child_failure_code(child) == "recursion_limit":
            active.cancel_reason = SubagentReasonCode.BUDGET_EXCEEDED
            active.budget_detail = "子 Agent 达到 max_turns"
            return budget_exceeded_result(active)
        return failure_result(
            active,
            SubagentStatus.FAILED,
            SubagentReasonCode.EXECUTION_FAILED,
            SubagentFailurePhase.RUNNING,
            RuntimeError(outcome_error or "子 Agent 运行失败"),
        )
    assert active.budget is not None
    facts = extract_child_facts(child)
    return SubagentResult(
        delegation_id=active.request.delegation_id,
        status=SubagentStatus.COMPLETED,
        child_run_id=active.child_run_id,
        attempt_id=active.attempt_id,
        summary=child_summary(child, returned, limit=active.budget.max_output_chars),
        diagnostics=tuple(active.diagnostics),
        findings=facts.findings,
        evidence=facts.evidence,
        usage=facts.usage,
        artifact=facts.artifact,
    )


def subscribe_child(
    active: ActiveDelegation,
    on_event: Callable[[AgentEvent], Any] | None,
) -> Callable[[], None] | None:
    """Subscribe once and enrich child events with delegation identity."""
    subscribe = getattr(active.session, "subscribe", None)
    if not callable(subscribe):
        return None

    def handle(event: AgentEvent) -> None:
        event_child_run_id = getattr(event, "run_id", None) or child_run_id(active.session)
        if event_child_run_id:
            active.child_run_id = event_child_run_id
        observe_budget(active, event)
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
            record_diagnostic(active, diagnostic("子事件回调", exc))
        else:
            if inspect.isawaitable(result):
                task = asyncio.create_task(observe_event(result, active))
                active.event_tasks.add(task)
                task.add_done_callback(active.event_tasks.discard)

    return subscribe(handle)


def observe_budget(active: ActiveDelegation, event: AgentEvent) -> None:
    """Count child lifecycle events and request synchronous cancellation at a limit."""
    budget = active.budget
    if budget is None or active.cancel_requested:
        return
    if event.type == EventType.TURN_START:
        active.turn_count += 1
        if active.turn_count > budget.max_turns:
            request_budget_cancel(active, f"子 Agent 达到 max_turns={budget.max_turns}")
        return
    if event.type not in {EventType.TOOL_QUEUED, EventType.TOOL_EXECUTION_QUEUED}:
        return
    metadata = dict(getattr(event, "metadata", {}) or {})
    call_id = (
        getattr(event, "tool_call_id", None)
        or metadata.get("tool_call_id")
        or getattr(event, "operation_id", None)
        or metadata.get("operation_id")
    )
    key = str(call_id or f"anonymous-{active.tool_call_count}")
    if key in active.seen_tool_call_ids:
        return
    active.seen_tool_call_ids.add(key)
    active.tool_call_count += 1
    if active.tool_call_count > budget.max_tool_calls:
        request_budget_cancel(
            active,
            f"子 Agent 达到 max_tool_calls={budget.max_tool_calls}",
        )


def request_budget_cancel(active: ActiveDelegation, detail: str) -> None:
    """Cancel a child from a synchronous event callback without awaiting it."""
    if active.cancel_requested:
        return
    active.cancel_requested = True
    active.cancel_reason = SubagentReasonCode.BUDGET_EXCEEDED
    active.budget_detail = detail
    abort = getattr(active.session, "abort", None)
    if callable(abort):
        try:
            abort()
        except Exception as exc:  # noqa: BLE001 - cancellation is diagnostic
            record_diagnostic(active, diagnostic("预算取消子 Session", exc))
    task = active.task
    if task is not None and not task.done():
        task.cancel()


__all__ = [
    "ChildSessionFactory",
    "observe_budget",
    "request_budget_cancel",
    "run_active",
    "subscribe_child",
]
