"""Structured state and outcomes for one session runtime run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from codeagent.core.context_budget import ContextBudgetSnapshot
from codeagent.core.context_preflight import ContextPreflightResult
from codeagent.session.persistence.models import UsageStats

class RunPhase(StrEnum):
    """Observable phases owned by the session runtime."""

    IDLE = "idle"
    STARTING = "starting"
    MODEL_WAIT = "model_wait"
    TOOL_RUNNING = "tool_running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONTINUING = "continuing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    FINALIZING = "finalizing"


class CommitStatus(StrEnum):
    """Persistence boundary reached by a run."""

    NOT_ATTEMPTED = "not_attempted"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    PERSISTENCE_FAILED = "persistence_failed"
    COMPACTION_FAILED = "compaction_failed"
    UNCERTAIN = "uncertain"


_ALLOWED_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.IDLE: frozenset({RunPhase.STARTING}),
    RunPhase.STARTING: frozenset(
        {
            RunPhase.MODEL_WAIT,
            RunPhase.TOOL_RUNNING,
            RunPhase.AWAITING_CONFIRMATION,
            RunPhase.CONTINUING,
            RunPhase.COMPLETED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.FINALIZING,
        }
    ),
    RunPhase.MODEL_WAIT: frozenset(
        {
            RunPhase.TOOL_RUNNING,
            RunPhase.AWAITING_CONFIRMATION,
            RunPhase.CONTINUING,
            RunPhase.COMPLETED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.FINALIZING,
        }
    ),
    RunPhase.TOOL_RUNNING: frozenset(
        {
            RunPhase.AWAITING_CONFIRMATION,
            RunPhase.MODEL_WAIT,
            RunPhase.CONTINUING,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.FINALIZING,
        }
    ),
    RunPhase.AWAITING_CONFIRMATION: frozenset(
        {
            RunPhase.TOOL_RUNNING,
            RunPhase.MODEL_WAIT,
            RunPhase.CONTINUING,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.FINALIZING,
        }
    ),
    RunPhase.CONTINUING: frozenset(
        {
            RunPhase.MODEL_WAIT,
            RunPhase.TOOL_RUNNING,
            RunPhase.AWAITING_CONFIRMATION,
            RunPhase.COMPLETED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.FINALIZING,
        }
    ),
    RunPhase.COMPLETED: frozenset({RunPhase.FINALIZING}),
    RunPhase.FAILED: frozenset({RunPhase.FINALIZING}),
    RunPhase.CANCELLED: frozenset({RunPhase.FINALIZING}),
    RunPhase.FINALIZING: frozenset(
        {RunPhase.IDLE, RunPhase.COMPLETED, RunPhase.FAILED, RunPhase.CANCELLED}
    ),
}


@dataclass(frozen=True)
class RuntimeFailure:
    """Machine-readable failure information for a completed run."""

    code: str
    message: str
    phase: str
    retryable: bool = False
    side_effect_state: str = "none"
    cleanup_uncertain: bool = False
    operation_id: str | None = None
    cause_type: str | None = None
    budget_status: str | None = None
    input_tokens: int | None = None
    input_budget: int | None = None
    headroom: int | None = None
    window_source: str | None = None

    def as_metadata(self) -> dict[str, Any]:
        """Return fields safe to attach to a session event."""
        metadata = {
            "error": self.message,
            "error_code": self.code,
            "error_message": self.message,
            "phase": self.phase,
            "retryable": self.retryable,
            "side_effect_state": self.side_effect_state,
            "cleanup_uncertain": self.cleanup_uncertain,
            "operation_id": self.operation_id,
            "cause_type": self.cause_type,
        }
        if self.budget_status is not None:
            metadata.update(
                {
                    "budget_status": self.budget_status,
                    "input_tokens": self.input_tokens,
                    "input_budget": self.input_budget,
                    "headroom": self.headroom,
                    "window_source": self.window_source,
                }
            )
        return metadata


@dataclass(frozen=True)
class RunOutcome:
    """Final result of a run before the runtime returns to idle."""

    run_id: str
    phase: RunPhase
    failure: RuntimeFailure | None = None
    commit_status: CommitStatus = CommitStatus.NOT_ATTEMPTED

    @property
    def completed(self) -> bool:
        """Whether the model turn reached a committed completed boundary."""
        return (
            self.phase is RunPhase.COMPLETED
            and self.commit_status is CommitStatus.COMMITTED
        )

    def as_metadata(self) -> dict[str, Any]:
        """Return stable fields for the terminal session event."""
        metadata: dict[str, Any] = {
            "run_outcome": self.phase.value,
            "commit_status": self.commit_status.value,
        }
        if self.failure is not None:
            metadata.update(self.failure.as_metadata())
        return metadata


@dataclass
class RunState:
    """Mutable state machine for one session run."""

    run_id: str | None = None
    session_id: str | None = None
    phase: RunPhase = RunPhase.IDLE
    previous_phase: RunPhase | None = None
    failure: RuntimeFailure | None = None
    cancellation_requested: bool = False
    terminal_emitted: bool = False
    sequence: int = 0
    active_operation_ids: set[str] = field(default_factory=set)

    def transition(self, target: RunPhase) -> None:
        """Move to a legal phase, rejecting accidental lifecycle jumps."""
        if target == self.phase:
            return
        if target not in _ALLOWED_TRANSITIONS[self.phase]:
            raise ValueError(
                f"invalid run phase transition: {self.phase.value} -> {target.value}"
            )
        self.previous_phase = self.phase
        self.phase = target

    def next_sequence(self) -> int:
        """Return the next monotonic event sequence number for this run."""
        self.sequence += 1
        return self.sequence


@dataclass
class SessionBudgetState:
    """Runtime-only budget and provider usage state for the active session."""

    latest_estimate: ContextBudgetSnapshot | None = None
    latest_preflight: ContextPreflightResult | None = None
    latest_actual_usage: UsageStats | None = None

    def reset_request(self) -> None:
        """Clear request-local observations before a new session run."""
        self.latest_estimate = None
        self.latest_preflight = None
        self.latest_actual_usage = None

    def record_estimate(self, snapshot: ContextBudgetSnapshot) -> None:
        self.latest_estimate = snapshot

    def record_preflight(self, result: ContextPreflightResult) -> None:
        self.latest_preflight = result

    def record_actual_usage(self, payload: dict[str, Any]) -> None:
        self.latest_actual_usage = UsageStats(
            input_tokens=int(payload.get("input_tokens", 0) or 0),
            output_tokens=int(payload.get("output_tokens", 0) or 0),
            reasoning_tokens=int(payload.get("reasoning_tokens", 0) or 0),
            cached_tokens=int(payload.get("cached_tokens", 0) or 0),
        )


__all__ = [
    "CommitStatus",
    "RunOutcome",
    "RunPhase",
    "RunState",
    "SessionBudgetState",
    "RuntimeFailure",
]
