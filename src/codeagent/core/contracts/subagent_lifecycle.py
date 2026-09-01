"""Lifecycle enums and failure values for delegated Subagents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from codeagent.core.contracts.errors import (
    SubagentContractError,
    SubagentRequestError,
)

__all__ = [
    "SubagentFailure",
    "SubagentFailurePhase",
    "SubagentReasonCode",
    "SubagentStatus",
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


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SubagentRequestError(f"{name} must be a non-empty string")
