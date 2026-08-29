"""Turn coordination extracted from the public ``AgentSession`` facade."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message
from codeagent.core.contracts.ports import ApprovalPolicy
from codeagent.session.constants import SUMMARY_ID_PREFIX, SUMMARY_PREFIX
from codeagent.session.persistence.errors import (
    PersistenceCancellationUncertainError,
    PersistenceUncertainError,
)
from codeagent.session.runtime.error_policy import classify_error
from codeagent.session.runtime.state import CommitStatus, RunOutcome, RunPhase

if TYPE_CHECKING:
    from codeagent.session.session import AgentSession


class SessionRunCoordinator:
    """Run one session turn and own its commit/finalization sequence."""

    def __init__(self, owner: AgentSession) -> None:
        self._owner = owner
        self._pending_outcome: RunOutcome | None = None

    async def run(
        self,
        text: str,
        recursion_limit: int | None,
        policy: ApprovalPolicy | None,
    ) -> None:
        run_id, history, before_ids = self._start(text)
        self._pending_outcome = None
        outcome: RunOutcome | None = None
        try:
            outcome = await self._run_body(text, run_id, history, before_ids, recursion_limit, policy)
        except asyncio.CancelledError:
            outcome = self._pending_outcome or RunOutcome(
                run_id=run_id,
                phase=RunPhase.CANCELLED,
                commit_status=CommitStatus.UNCERTAIN,
            )
            raise
        finally:
            self._finish(run_id, before_ids, outcome)
            await self._owner._drain_lifecycle_hooks()

    def _start(self, text: str) -> tuple[str, list[Message], set[str]]:
        owner = self._owner
        owner._budget_state.reset_request()
        run_id = owner._runtime.start_run()
        metadata: dict[str, Any] = {"phase": owner._runtime.phase.value}
        if owner._previous_session_id:
            metadata["previous_session_id"] = owner._previous_session_id
        owner._emit(AgentEvent(EventType.SESSION_STARTED, payload=text, metadata=metadata), run_id)
        history = list(owner._history)
        if owner._summary is not None and owner._summary_entry_id:
            history.insert(
                0,
                Message(
                    role="user",
                    content=SUMMARY_PREFIX + owner._summary,
                    id=f"{SUMMARY_ID_PREFIX}{owner._summary_entry_id}",
                    parent_id=owner._summary_entry_id,
                ),
            )
        return run_id, history, {message.id for message in owner._history}

    async def _run_body(
        self,
        text: str,
        run_id: str,
        history: list[Message],
        before_ids: set[str],
        recursion_limit: int | None,
        policy: ApprovalPolicy | None,
    ) -> RunOutcome:
        owner = self._owner
        try:
            new_messages = await owner._runtime.execute(
                owner._config,
                text,
                history=history,
                recursion_limit=recursion_limit or owner._recursion_limit,
                tool_timeout=owner._tool_timeout,
                policy=owner._policy if policy is None else policy,
                transform_context=owner._transform_context,
            )
        except asyncio.CancelledError:
            self._pending_outcome = self._cancelled(run_id, before_ids)
            raise
        except Exception as exc:
            owner._rollback(before_ids)
            return self._failure(text, run_id, exc, owner._runtime.state.previous_phase or owner._runtime.phase, owner._rollback_status())

        owner._runtime.begin_finalization()
        try:
            await self._commit(history, new_messages, before_ids)
        except asyncio.CancelledError:
            self._pending_outcome = self._cancelled(run_id, before_ids)
            raise
        except Exception as exc:
            return self._failure(text, run_id, exc, "persistence", CommitStatus.PERSISTENCE_FAILED)

        try:
            await owner._maybe_auto_compact()
        except asyncio.CancelledError as exc:
            self._pending_outcome = RunOutcome(
                run_id=run_id,
                phase=RunPhase.COMPLETED,
                commit_status=CommitStatus.COMMITTED,
                post_commit_status=(
                    "persistence_uncertain"
                    if isinstance(exc, PersistenceCancellationUncertainError)
                    else "compaction_cancelled"
                ),
            )
            raise
        except PersistenceUncertainError:
            return RunOutcome(
                run_id=run_id,
                phase=RunPhase.COMPLETED,
                commit_status=CommitStatus.COMMITTED,
                post_commit_status="persistence_uncertain",
            )
        except Exception:
            return RunOutcome(
                run_id=run_id,
                phase=RunPhase.COMPLETED,
                commit_status=CommitStatus.COMMITTED,
                post_commit_status="compaction_failed",
            )
        return RunOutcome(
            run_id=run_id,
            phase=RunPhase.COMPLETED,
            commit_status=CommitStatus.COMMITTED,
        )

    async def _commit(
        self,
        history: list[Message],
        new_messages: list[Message],
        before_ids: set[str],
    ) -> None:
        owner = self._owner
        kept_history = [message for message in [*history, *new_messages] if not message.id.startswith(SUMMARY_ID_PREFIX)]
        owner._link_persistence_parents(new_messages)
        if owner._summary_entry_id:
            for message in kept_history:
                if message.id not in before_ids and message.role == "user":
                    message.parent_id = owner._summary_entry_id
                    break
        new_messages = [message for message in kept_history if message.id not in before_ids]
        await owner._persistence.commit_turn_async(
            new_messages,
            owner._runtime.turn_usage,
            context_tokens=owner._last_input_tokens,
        )
        owner._history = kept_history

    def _failure(
        self,
        text: str,
        run_id: str,
        exc: Exception,
        phase: Any,
        commit_status: CommitStatus,
    ) -> RunOutcome:
        owner = self._owner
        failure = classify_error(
            exc,
            phase=phase,
            side_effect_state=owner._runtime.side_effect_state,
            cleanup_uncertain=owner._runtime.cleanup_uncertain,
        )
        owner._runtime.set_failure(failure)
        owner._runtime.last_failure = {**failure.as_metadata(), "prompt": text}
        owner._emit(AgentEvent(EventType.ERROR, payload=failure.message, metadata=failure.as_metadata()), run_id)
        return RunOutcome(run_id=run_id, phase=RunPhase.FAILED, failure=failure, commit_status=commit_status)

    def _cancelled(
        self,
        run_id: str,
        before_ids: set[str],
        commit_status: CommitStatus | None = None,
        *,
        rollback: bool = True,
    ) -> RunOutcome:
        owner = self._owner
        if rollback:
            owner._rollback(before_ids)
        owner._emit(
            AgentEvent(
                EventType.RUN_CANCELLED,
                metadata={
                    "phase": RunPhase.CANCELLED.value,
                    "side_effect_state": owner._runtime.side_effect_state,
                    "cleanup_uncertain": owner._runtime.cleanup_uncertain,
                    "cleanup_status": owner._runtime.cleanup_status,
                },
            ),
            run_id,
        )
        return RunOutcome(
            run_id=run_id,
            phase=RunPhase.CANCELLED,
            commit_status=commit_status or owner._rollback_status(),
        )

    def _finish(
        self,
        run_id: str,
        before_ids: set[str],
        outcome: RunOutcome | None,
    ) -> None:
        owner = self._owner
        if outcome is None:
            owner._rollback(before_ids)
            outcome = RunOutcome(run_id=run_id, phase=RunPhase.FAILED, commit_status=CommitStatus.ROLLED_BACK)
        owner._runtime.finish_run(outcome)
        if owner._runtime.state.terminal_emitted:
            return
        owner._runtime.state.terminal_emitted = True
        failure = outcome.failure or owner._runtime.last_failure
        owner._emit(
            AgentEvent(
                EventType.TURN_END,
                metadata={
                    "terminal_phase": "error" if outcome.phase is RunPhase.FAILED else "idle",
                    "phase": outcome.phase.value,
                    "run_outcome": outcome.phase.value,
                    "commit_status": outcome.commit_status.value,
                    "post_commit_status": outcome.post_commit_status,
                    "side_effect_state": owner._runtime.side_effect_state,
                    "cleanup_status": owner._runtime.cleanup_status,
                    "cleanup_uncertain": owner._runtime.cleanup_uncertain,
                    "error_code": (
                        failure.get("error_code")
                        if isinstance(failure, dict)
                        else failure.code if failure is not None else None
                    ),
                },
            ),
            run_id,
        )


__all__ = ["SessionRunCoordinator"]
