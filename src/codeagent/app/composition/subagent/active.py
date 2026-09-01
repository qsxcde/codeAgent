"""Mutable execution record for one active Subagent delegation."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from codeagent.core.contracts.subagent_state import SubagentState
from codeagent.core.contracts.subagents import (
    SubagentReasonCode,
    SubagentRequest,
    SubagentResult,
)

from .budget import EffectiveSubagentBudget
from .runner_support import DEFAULT_CLEANUP_TIMEOUT


@dataclass
class ActiveDelegation:
    """Runtime-only state; it never crosses the parent result boundary."""

    request: SubagentRequest
    attempt_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session: Any = None
    task: asyncio.Task[Any] | None = None
    execution_task: asyncio.Task[Any] | None = None
    child_run_id: str | None = None
    child_sequence: int | None = None
    cancel_requested: bool = False
    cancel_reason: SubagentReasonCode | None = None
    unsubscribe: Callable[[], None] | None = None
    event_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    diagnostics: list[str] = field(default_factory=list)
    budget: EffectiveSubagentBudget | None = None
    cleanup_timeout: float = DEFAULT_CLEANUP_TIMEOUT
    cleanup_uncertain: bool = False
    cleanup_error: str | None = None
    budget_detail: str | None = None
    turn_count: int = 0
    tool_call_count: int = 0
    seen_tool_call_ids: set[str] = field(default_factory=set)
    state: SubagentState = field(init=False)
    event_forwarding_closed: bool = False

    def __post_init__(self) -> None:
        self.state = SubagentState(self.request)

    @property
    def terminal_result(self) -> SubagentResult | None:
        """Return the result committed by the delegation state machine."""
        return self.state.terminal_result


__all__ = ["ActiveDelegation"]
