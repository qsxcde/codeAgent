"""Independent lifecycle state machine for one delegated Subagent run."""

from __future__ import annotations

from dataclasses import dataclass

from codeagent.core.contracts.errors import SubagentRequestError, SubagentStateError
from codeagent.core.contracts.subagents import (
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
    _require_text,
)

__all__ = ["SubagentState"]


_ALLOWED_TRANSITIONS: dict[SubagentStatus, frozenset[SubagentStatus]] = {
    SubagentStatus.CREATED: frozenset({SubagentStatus.QUEUED, SubagentStatus.REJECTED}),
    SubagentStatus.QUEUED: frozenset(
        {SubagentStatus.STARTING, SubagentStatus.CANCELLED, SubagentStatus.REJECTED}
    ),
    SubagentStatus.STARTING: frozenset(
        {
            SubagentStatus.RUNNING,
            SubagentStatus.FAILED,
            SubagentStatus.TIMED_OUT,
            SubagentStatus.CANCELLING,
        }
    ),
    SubagentStatus.RUNNING: frozenset(
        {
            SubagentStatus.WAITING_CONFIRMATION,
            SubagentStatus.COMPLETED,
            SubagentStatus.FAILED,
            SubagentStatus.CANCELLING,
        }
    ),
    SubagentStatus.WAITING_CONFIRMATION: frozenset(
        {SubagentStatus.RUNNING, SubagentStatus.CANCELLING}
    ),
    SubagentStatus.CANCELLING: frozenset(
        {SubagentStatus.CANCELLED, SubagentStatus.TIMED_OUT}
    ),
    SubagentStatus.COMPLETED: frozenset(),
    SubagentStatus.FAILED: frozenset(),
    SubagentStatus.TIMED_OUT: frozenset(),
    SubagentStatus.CANCELLED: frozenset(),
    SubagentStatus.REJECTED: frozenset(),
}


@dataclass
class SubagentState:
    """Mutable lifecycle state for one delegation, independent of Session."""

    request: SubagentRequest
    status: SubagentStatus = SubagentStatus.CREATED
    previous_status: SubagentStatus | None = None
    child_run_id: str | None = None
    attempt_id: str | None = None
    cancellation_requested: bool = False
    terminal_emitted: bool = False
    sequence: int = 0
    terminal_result: SubagentResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, SubagentRequest):
            raise SubagentRequestError("state request must be a SubagentRequest")
        try:
            self.status = SubagentStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise SubagentStateError(f"unknown Subagent status: {self.status!r}") from exc
        if self.status.is_terminal:
            if self.terminal_result is None:
                raise SubagentStateError("terminal state requires a terminal result")
            if self.terminal_result.status is not self.status:
                raise SubagentStateError("terminal result status does not match state")
            if self.terminal_result.delegation_id != self.delegation_id:
                raise SubagentStateError("terminal result delegation_id does not match state")
            self.terminal_emitted = True
        elif self.terminal_result is not None:
            raise SubagentStateError("non-terminal state cannot have a terminal result")

    @property
    def delegation_id(self) -> str:
        return self.request.delegation_id

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    def transition(
        self,
        target: SubagentStatus,
        *,
        result: SubagentResult | None = None,
        child_run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        """Move to a legal status and optionally commit its terminal result."""
        try:
            target = SubagentStatus(target)
        except (TypeError, ValueError) as exc:
            raise SubagentStateError(f"unknown Subagent status: {target!r}") from exc
        if target is self.status:
            if target.is_terminal:
                if result is not None and result != self.terminal_result:
                    raise SubagentStateError("conflicting duplicate terminal result")
                return
            self._set_identity(child_run_id=child_run_id, attempt_id=attempt_id)
            return
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise SubagentStateError(
                f"invalid Subagent status transition: {self.status.value} -> {target.value}"
            )
        if target.is_terminal:
            self._commit_terminal(target, result)
        else:
            self.previous_status = self.status
            self.status = target
            self._set_identity(child_run_id=child_run_id, attempt_id=attempt_id)
            if target is SubagentStatus.CANCELLING:
                self.cancellation_requested = True

    def finish(self, result: SubagentResult) -> None:
        """Commit one terminal result through the transition guard."""
        self.transition(result.status, result=result)

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence

    def _set_identity(self, *, child_run_id: str | None, attempt_id: str | None) -> None:
        for name, value in (("child_run_id", child_run_id), ("attempt_id", attempt_id)):
            if value is None:
                continue
            _require_text(value, name)
            existing = getattr(self, name)
            if existing is not None and existing != value:
                raise SubagentStateError(f"{name} cannot change within one attempt")
            setattr(self, name, value)

    def _commit_terminal(
        self,
        target: SubagentStatus,
        result: SubagentResult | None,
    ) -> None:
        if not isinstance(result, SubagentResult):
            raise SubagentStateError("terminal transition requires a SubagentResult")
        if result.status is not target:
            raise SubagentStateError("terminal result status does not match transition")
        if result.delegation_id != self.delegation_id:
            raise SubagentStateError("terminal result delegation_id does not match state")
        self.previous_status = self.status
        self.status = target
        self.terminal_result = result
        self.terminal_emitted = True
        self._set_identity(child_run_id=result.child_run_id, attempt_id=result.attempt_id)
        if target in {SubagentStatus.CANCELLED, SubagentStatus.TIMED_OUT}:
            self.cancellation_requested = True
