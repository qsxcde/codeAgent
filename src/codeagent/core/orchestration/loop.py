"""ReAct loop public entrypoints and lifecycle/error event handling."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.errors import (
    ContextPreparationError,
    ContextPreflightError,
)
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.execution.runtime import ToolExecutionRuntime
from codeagent.core.orchestration.errors import RecursionLimitError
from codeagent.core.contracts.messages import CleanupStatus, Message, new_id
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.core.orchestration.turn import run_turn

DEFAULT_RECURSION_LIMIT = 50


async def _run_agent_loop(
    context: AgentContext,
    config: AgentLoopConfig,
    prompt: str | None,
    *,
    emit: Callable[[AgentEvent], Any] | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    run_id: str | None = None,
) -> list[Message]:
    emit = emit or (lambda _event: None)
    run_id = run_id or new_id()

    def publish(event: AgentEvent) -> None:
        metadata = dict(event.metadata or {})
        metadata.setdefault("run_id", run_id)
        emit(replace(event, metadata=metadata, run_id=event.run_id or run_id))

    config = _ensure_runtime(config)
    _reset_cleanup_diagnostics(config)
    working, new_messages = _start_context(context, prompt)
    publish(AgentEvent(EventType.AGENT_START))
    try:
        for iteration in range(max(1, recursion_limit)):
            should_stop = await run_turn(
                config,
                iteration,
                iteration >= max(1, recursion_limit) - 1,
                publish,
                working,
                new_messages,
            )
            if should_stop:
                break
        else:
            raise RecursionLimitError()
    except asyncio.CancelledError:
        publish(AgentEvent(EventType.ABORTED, metadata=_cleanup_metadata(config)))
        raise
    except Exception as exc:
        publish(AgentEvent(EventType.ERROR, payload=str(exc), metadata=_error_metadata(exc)))
        raise
    publish(AgentEvent(EventType.AGENT_END, payload=new_messages))
    return new_messages


def _ensure_runtime(config: AgentLoopConfig) -> AgentLoopConfig:
    if config.tool_runtime is not None:
        return config
    return replace(config, tool_runtime=ToolExecutionRuntime())


def _reset_cleanup_diagnostics(config: AgentLoopConfig) -> None:
    reset_cleanup = getattr(config.tool_runtime, "reset_cleanup_diagnostics", None)
    if callable(reset_cleanup):
        reset_cleanup()


def _start_context(
    context: AgentContext,
    prompt: str | None,
) -> tuple[AgentContext, list[Message]]:
    working = context.copy()
    new_messages: list[Message] = []
    if prompt is not None:
        user = Message(role="user", content=prompt)
        working.messages.append(user)
        new_messages.append(user)
    return working, new_messages


def _cleanup_metadata(config: AgentLoopConfig) -> dict[str, Any]:
    runtime = config.tool_runtime
    if runtime is None:
        return {}
    status = getattr(runtime, "cleanup_status", None)
    if not status or status == CleanupStatus.NOT_REQUIRED:
        return {}
    metadata: dict[str, Any] = {
        "cleanup_status": status,
        "cleanup_uncertain": bool(getattr(runtime, "cleanup_uncertain", False)),
    }
    error = getattr(runtime, "cleanup_error", None)
    if error:
        metadata["cleanup_error"] = error
    return metadata


def _error_metadata(error: Exception) -> dict[str, Any]:
    metadata: dict[str, Any] = {"error_type": type(error).__name__}
    if not isinstance(error, ContextPreparationError):
        return metadata
    metadata.update(
        {
            "error_code": error.code,
            "phase": error.phase,
            "cause_type": type(error.cause).__name__,
        }
    )
    if isinstance(error, ContextPreflightError):
        snapshot = error.result.snapshot
        metadata.update(
            {
                "budget_status": error.result.status,
                "budget_allowed": error.result.allowed,
                "input_tokens": snapshot.input_tokens,
                "input_budget": snapshot.input_budget,
                "headroom": snapshot.headroom,
                "window_source": snapshot.window_source,
                "warning_boundary": error.result.warning_boundary,
            }
        )
    return metadata


async def run_agent_loop(
    context: AgentContext,
    config: AgentLoopConfig,
    prompt: str,
    *,
    emit: Callable[[AgentEvent], Any] | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    run_id: str | None = None,
) -> list[Message]:
    """Run a new prompt against a copied in-memory context."""
    return await _run_agent_loop(
        context,
        config,
        prompt,
        emit=emit,
        recursion_limit=recursion_limit,
        run_id=run_id,
    )


async def run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    *,
    emit: Callable[[AgentEvent], Any] | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    run_id: str | None = None,
) -> list[Message]:
    """Continue from a user/tool-result tail without adding a prompt."""
    context.validate_continue()
    return await _run_agent_loop(
        context,
        config,
        None,
        emit=emit,
        recursion_limit=recursion_limit,
        run_id=run_id,
    )


__all__ = [
    "DEFAULT_RECURSION_LIMIT",
    "RecursionLimitError",
    "run_agent_loop",
    "run_agent_loop_continue",
]
