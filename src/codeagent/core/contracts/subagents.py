"""Provider-neutral contracts for delegated Subagent runs."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from codeagent.core.contracts.errors import (
    SubagentContractError,
    SubagentRequestError,
)
from codeagent.core.contracts.events import AgentEvent

__all__ = [
    "SubagentBudget",
    "SubagentContextItem",
    "SubagentFailure",
    "SubagentFailurePhase",
    "SubagentReasonCode",
    "SubagentRequest",
    "SubagentResult",
    "SubagentRunner",
    "SubagentStatus",
    "SubagentEventSink",
]


class SubagentStatus(StrEnum):
    """Lifecycle status of one parent-to-child delegation."""

    CREATED = "created"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


class SubagentReasonCode(StrEnum):
    """Stable reasons orthogonal to the top-level lifecycle status."""

    INVALID_REQUEST = "invalid_request"
    PERMISSION_DENIED = "permission_denied"
    DEPTH_EXCEEDED = "depth_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMEOUT = "timeout"
    PARENT_CANCELLED = "parent_cancelled"
    CONFIRMATION_REJECTED = "confirmation_rejected"
    STARTUP_FAILED = "startup_failed"
    EXECUTION_FAILED = "execution_failed"


class SubagentFailurePhase(StrEnum):
    """Lifecycle points at which a structured failure can be observed."""

    VALIDATION = "validation"
    QUEUE = "queue"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    CANCELLING = "cancelling"


_TERMINAL_STATUSES = frozenset(
    {
        SubagentStatus.COMPLETED,
        SubagentStatus.FAILED,
        SubagentStatus.TIMED_OUT,
        SubagentStatus.CANCELLED,
        SubagentStatus.REJECTED,
    }
)


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
    profile: str = "read_only"
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


@dataclass(frozen=True)
class SubagentFailure:
    """Safe, machine-readable failure information for a child run."""

    reason_code: str
    message: str
    phase: str
    retryable: bool = False
    side_effect_state: str = "none"
    cleanup_uncertain: bool = False

    def __post_init__(self) -> None:
        _require_text(self.reason_code, "reason_code")
        _require_text(self.message, "failure message")
        _require_text(self.phase, "failure phase")
        _require_text(self.side_effect_state, "side_effect_state")
        if not isinstance(self.retryable, bool):
            raise SubagentContractError("retryable must be a bool", code="invalid_failure")
        if not isinstance(self.cleanup_uncertain, bool):
            raise SubagentContractError(
                "cleanup_uncertain must be a bool", code="invalid_failure"
            )

    def as_metadata(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "error": self.message,
            "error_message": self.message,
            "phase": self.phase,
            "retryable": self.retryable,
            "side_effect_state": self.side_effect_state,
            "cleanup_uncertain": self.cleanup_uncertain,
        }


@dataclass(frozen=True)
class SubagentResult:
    """Immutable terminal result returned to the parent run."""

    delegation_id: str
    status: SubagentStatus
    child_run_id: str | None = None
    attempt_id: str | None = None
    summary: str = ""
    failure: SubagentFailure | None = None
    diagnostics: tuple[str, ...] = ()
    cleanup_uncertain: bool = False

    def __post_init__(self) -> None:
        _require_text(self.delegation_id, "delegation_id")
        try:
            status = SubagentStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise SubagentContractError(
                f"unknown Subagent status: {self.status!r}", code="invalid_result"
            ) from exc
        object.__setattr__(self, "status", status)
        if not status.is_terminal:
            raise SubagentContractError(
                "SubagentResult status must be terminal", code="invalid_result"
            )
        if status is SubagentStatus.COMPLETED and self.failure is not None:
            raise SubagentContractError(
                "completed SubagentResult cannot contain a failure", code="invalid_result"
            )
        if status is not SubagentStatus.COMPLETED and self.failure is None:
            raise SubagentContractError(
                "non-completed SubagentResult requires a failure", code="invalid_result"
            )
        for name in ("child_run_id", "attempt_id"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        if not isinstance(self.diagnostics, tuple):
            object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not all(isinstance(item, str) for item in self.diagnostics):
            raise SubagentContractError("diagnostics must contain strings", code="invalid_result")
        if not isinstance(self.cleanup_uncertain, bool):
            raise SubagentContractError(
                "cleanup_uncertain must be a bool", code="invalid_result"
            )


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
