"""Provider-neutral contracts for delegated Subagent runs."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from codeagent.core.contracts.errors import SubagentRequestError
from codeagent.core.contracts.events import AgentEvent

from .subagent_lifecycle import (
    SubagentFailure,
    SubagentFailurePhase,
    SubagentReasonCode,
    SubagentStatus,
)
from .subagent_result import SubagentResult
from .subagent_results import (
    MAX_SUBAGENT_EVIDENCE,
    MAX_SUBAGENT_FINDINGS,
    MAX_SUBAGENT_SUMMARY_CHARS,
    SubagentArtifact,
    SubagentEvidence,
    SubagentFinding,
    SubagentUsage,
)

__all__ = [
    "MAX_SUBAGENT_EVIDENCE",
    "MAX_SUBAGENT_FINDINGS",
    "MAX_SUBAGENT_SUMMARY_CHARS",
    "SubagentArtifact",
    "SubagentBudget",
    "SubagentContextItem",
    "SubagentEvidence",
    "SubagentFailure",
    "SubagentFailurePhase",
    "SubagentFinding",
    "SubagentReasonCode",
    "SubagentRequest",
    "SubagentResult",
    "SubagentRunner",
    "SubagentStatus",
    "SubagentEventSink",
    "SubagentUsage",
]


@dataclass(frozen=True)
class SubagentContextItem:
    """A small immutable fact explicitly handed from parent to child."""

    kind: str
    content: str
    source: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.kind, "context kind")
        _require_text(self.content, "context content")
        if self.source is not None:
            _require_text(self.source, "context source")


@dataclass(frozen=True)
class SubagentBudget:
    """Optional positive limits owned by one child run."""

    max_turns: int | None = None
    max_tool_calls: int | None = None
    timeout_seconds: float | None = None
    max_output_chars: int | None = None

    def __post_init__(self) -> None:
        _positive_int(self.max_turns, "max_turns")
        _positive_int(self.max_tool_calls, "max_tool_calls")
        _positive_number(self.timeout_seconds, "timeout_seconds")
        _positive_int(self.max_output_chars, "max_output_chars")


@dataclass(frozen=True)
class SubagentRequest:
    """Immutable handoff contract from a parent run to a child run."""

    delegation_id: str
    parent_run_id: str
    task: str
    profile: str = "explore"
    depth: int = 1
    max_depth: int = 1
    budget: SubagentBudget = field(default_factory=SubagentBudget)
    context: tuple[SubagentContextItem, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.delegation_id, "delegation_id")
        _require_text(self.parent_run_id, "parent_run_id")
        _require_text(self.task, "task")
        _require_text(self.profile, "profile")
        _nonnegative_int(self.depth, "depth")
        _nonnegative_int(self.max_depth, "max_depth")
        if self.depth > self.max_depth:
            raise SubagentRequestError(
                f"depth {self.depth} exceeds max_depth {self.max_depth}",
                code=SubagentReasonCode.DEPTH_EXCEEDED.value,
            )
        if not isinstance(self.budget, SubagentBudget):
            raise SubagentRequestError("budget must be a SubagentBudget")
        if not isinstance(self.context, tuple):
            object.__setattr__(self, "context", tuple(self.context))
        if not all(isinstance(item, SubagentContextItem) for item in self.context):
            raise SubagentRequestError("context must contain SubagentContextItem values")


SubagentEventSink = Callable[[AgentEvent], Awaitable[None] | None]


@runtime_checkable
class SubagentRunner(Protocol):
    """Port implemented by the application composition layer."""

    async def execute(
        self,
        request: SubagentRequest,
        *,
        on_event: SubagentEventSink | None = None,
    ) -> SubagentResult: ...

    async def cancel(self, delegation_id: str) -> bool: ...


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SubagentRequestError(f"{name} must be a non-empty string")


def _positive_int(value: int | None, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SubagentRequestError(f"{name} must be a positive integer")


def _nonnegative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SubagentRequestError(f"{name} must be a non-negative integer")


def _positive_number(value: float | None, name: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise SubagentRequestError(f"{name} must be a positive number")
