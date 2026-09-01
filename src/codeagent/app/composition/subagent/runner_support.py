"""Cleanup, result and diagnostic helpers for the serial Subagent runner."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

_MAX_DIAGNOSTIC_CHARS = 2_000
_MAX_DIAGNOSTICS = 8
DEFAULT_CLEANUP_TIMEOUT = 10.0


async def observe_event(result: Any, active: Any) -> None:
    try:
        await result
    except Exception as exc:  # noqa: BLE001 - observers are isolated
        record_diagnostic(active, diagnostic("子事件回调", exc))


async def cancel_session(active: Any, *, timeout: float | None = None) -> None:
    """Request cancellation and wait for known child work within one deadline."""
    deadline = time.monotonic() + _cleanup_timeout(active, timeout)
    session = active.session
    if session is not None:
        cancel_and_wait = getattr(session, "cancel_and_wait", None)
        if callable(cancel_and_wait):
            try:
                result = cancel_and_wait(timeout=_remaining(deadline))
                if inspect.isawaitable(result):
                    result = await _bounded(result, deadline)
                if result is False:
                    mark_cleanup_uncertain(active, "取消子 Session 未进入空闲", None)
            except asyncio.TimeoutError as exc:
                mark_cleanup_uncertain(active, "取消子 Session 超时", exc)
            except Exception as exc:  # noqa: BLE001 - cancellation is diagnostic
                mark_cleanup_uncertain(active, "取消子 Session", exc)
        else:
            abort = getattr(session, "abort", None)
            if callable(abort):
                try:
                    abort()
                except Exception as exc:  # noqa: BLE001 - cancellation is diagnostic
                    mark_cleanup_uncertain(active, "中止子 Session", exc)
    task = active.task
    if task is not None and not task.done() and task is not asyncio.current_task():
        task.cancel()
        try:
            await _bounded(asyncio.shield(task), deadline)
        except asyncio.CancelledError:
            # The child task reached the requested cancellation boundary.
            pass
        except asyncio.TimeoutError as exc:
            mark_cleanup_uncertain(active, "等待子运行取消", exc)
    elif session is None:
        execution = getattr(active, "execution_task", None)
        if (
            execution is not None
            and not execution.done()
            and execution is not asyncio.current_task()
        ):
            execution.cancel()
            try:
                await _bounded(asyncio.shield(execution), deadline)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError as exc:
                mark_cleanup_uncertain(active, "取消排队委派", exc)


async def close_active(active: Any, *, timeout: float | None = None) -> None:
    """Unsubscribe and close a child session without unbounded awaits."""
    deadline = time.monotonic() + _cleanup_timeout(active, timeout)
    if active.unsubscribe is not None:
        try:
            active.unsubscribe()
        except Exception as exc:  # noqa: BLE001 - cleanup is best effort
            mark_cleanup_uncertain(active, "取消子事件订阅", exc)
    if active.event_tasks:
        try:
            await _bounded(
                asyncio.gather(*active.event_tasks, return_exceptions=True), deadline
            )
        except asyncio.TimeoutError as exc:
            mark_cleanup_uncertain(active, "等待子事件观察任务", exc)
            for task in active.event_tasks:
                if not task.done():
                    task.cancel()
    close = getattr(active.session, "close", None)
    if callable(close):
        try:
            result = close()
            if inspect.isawaitable(result):
                await _bounded(result, deadline)
        except Exception as exc:  # noqa: BLE001 - preserve primary outcome
            mark_cleanup_uncertain(active, "关闭子 Session", exc)
    if active.task is not None and not active.task.done():
        active.task.cancel()
        mark_cleanup_uncertain(active, "子运行仍未结束", None)


def child_run_id(session: Any) -> str | None:
    value = getattr(session, "active_run_id", None)
    if value:
        return str(value)
    outcome = getattr(session, "last_outcome", None)
    value = getattr(outcome, "run_id", None)
    return str(value) if value else None


def child_summary(session: Any, returned: Any, *, limit: int = _MAX_DIAGNOSTIC_CHARS) -> str:
    if isinstance(returned, str):
        return bounded(returned, limit)
    history = getattr(session, "history", ())
    for message in reversed(list(history or ())):
        if getattr(message, "role", None) == "assistant":
            return bounded(str(getattr(message, "content", "") or ""), limit)
    return bounded(str(returned or ""), limit)


def child_outcome(session: Any) -> tuple[str | None, str | None]:
    """Read a Session outcome without importing Session into the runner."""
    outcome = getattr(session, "last_outcome", None)
    phase = getattr(outcome, "phase", None)
    phase_value = getattr(phase, "value", phase)
    if phase_value is None:
        return None, None
    failure = getattr(session, "last_failure", None)
    if isinstance(failure, dict):
        message = failure.get("error") or failure.get("error_message")
    else:
        message = None
    return str(phase_value), str(message) if message else None


def child_failure_code(session: Any) -> str | None:
    """Read a stable child failure code without importing Session."""
    failure = getattr(session, "last_failure", None)
    if isinstance(failure, dict):
        code = failure.get("error_code") or failure.get("code")
        return str(code) if code else None
    return None


def diagnostic(prefix: str, error: Exception) -> str:
    return bounded(f"{prefix}: {error}")


def record_diagnostic(active: Any, value: str) -> None:
    if len(active.diagnostics) < _MAX_DIAGNOSTICS:
        active.diagnostics.append(bounded(value))


def mark_cleanup_uncertain(active: Any, prefix: str, error: Exception | None) -> None:
    active.cleanup_uncertain = True
    if error is not None:
        active.cleanup_error = bounded(str(error))
        record_diagnostic(active, diagnostic(prefix, error))
    else:
        record_diagnostic(active, bounded(prefix))


def _cleanup_timeout(active: Any, timeout: float | None) -> float:
    value = timeout if timeout is not None else getattr(active, "cleanup_timeout", None)
    return max(0.001, float(value if value is not None else DEFAULT_CLEANUP_TIMEOUT))


def _remaining(deadline: float) -> float:
    return max(0.001, deadline - time.monotonic())


async def _bounded(awaitable: Any, deadline: float) -> Any:
    return await asyncio.wait_for(awaitable, timeout=_remaining(deadline))


def bounded(value: str, limit: int = _MAX_DIAGNOSTIC_CHARS) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


__all__ = [
    "bounded",
    "cancel_session",
    "child_failure_code",
    "child_run_id",
    "child_outcome",
    "child_summary",
    "close_active",
    "diagnostic",
    "mark_cleanup_uncertain",
    "observe_event",
    "record_diagnostic",
]
