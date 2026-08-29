"""Stateful compaction methods for ``AgentSession``."""

from __future__ import annotations

import asyncio
from typing import Any

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.session.compaction import (
    CompactionService,
    decide_auto_compaction,
)
from codeagent.session.compaction_runtime_budget import SessionCompactionBudgetMixin
from codeagent.session.compaction_runtime_events import (
    CompactionTrigger,
    SessionCompactionEventsMixin,
)
from codeagent.session.persistence.errors import (
    PersistenceCancellationUncertainError,
    PersistenceUncertainError,
)


class SessionCompactionMixin(SessionCompactionBudgetMixin, SessionCompactionEventsMixin):
    """Coordinate compaction without owning the session facade constructor."""

    async def compact(
        self,
        *,
        trigger: CompactionTrigger = "manual",
        budget_snapshot: ContextBudgetSnapshot | None = None,
    ) -> bool:
        """Run one serialized compaction and return whether history changed."""
        async with self._compaction_gate:
            snapshot = (
                await self._next_request_budget()
                if trigger == "auto"
                else budget_snapshot or await self._next_request_budget()
            )
            target = self._compaction_target(trigger, snapshot)
            if target is None:
                return False
            target_budget, reason = target
            return await self._execute_compaction(
                trigger, snapshot, target_budget, reason
            )

    def _compaction_target(
        self,
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot | None,
    ) -> tuple[int, str] | None:
        decision = (
            decide_auto_compaction(snapshot, self._compaction_policy)
            if snapshot is not None
            else None
        )
        if trigger != "auto":
            return self._manual_compaction_budget(decision), "manual compaction requested"
        if decision is None or not decision.should_compact:
            return None
        fingerprint = self._compaction_fingerprint(snapshot)
        if fingerprint == self._last_compaction_fingerprint:
            self._emit_skipped_compaction(
                trigger,
                snapshot,
                decision.target_budget,
                "already_compacted",
                "the same context has already been compacted",
            )
            return None
        if fingerprint == self._last_compaction_failure_fingerprint:
            self._emit_skipped_compaction(
                trigger,
                snapshot,
                decision.target_budget,
                "cooldown",
                "automatic compaction is cooling down after a failure",
            )
            return None
        return decision.target_budget, decision.reason

    async def _execute_compaction(
        self,
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot | None,
        target_budget: int,
        reason: str,
    ) -> bool:
        metadata = self._compaction_started_metadata(trigger, snapshot, target_budget, reason)
        self._emit(
            AgentEvent(EventType.COMPACTION_STARTED, metadata=metadata),
            self._runtime.active_run_id,
        )
        persistence_started = False

        async def append_compaction(entry: Any) -> str:
            nonlocal persistence_started
            persistence_started = True
            try:
                return await self._persistence.append_compaction_async(entry)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise PersistenceUncertainError("压缩记录持久化结果不确定") from exc

        try:
            result = await self._run_compaction_service(
                target_budget,
                trigger,
                append_compaction,
            )
        except asyncio.CancelledError:
            uncertain = self._handle_compaction_cancelled(metadata, persistence_started)
            if uncertain:
                raise PersistenceCancellationUncertainError(
                    "压缩记录持久化结果不确定"
                )
            raise
        except Exception as exc:
            self._handle_compaction_error(trigger, snapshot, metadata, exc)
            raise
        return self._publish_compaction_result(trigger, snapshot, target_budget, result)

    async def _run_compaction_service(
        self,
        target_budget: int,
        trigger: CompactionTrigger,
        append_compaction: Any,
    ) -> Any:
        service = CompactionService(
            self._summarizer,
            target_budget,
            append_compaction,
            min_recent_turns=self._compaction_policy.min_recent_turns,
            candidate_budget=self._estimate_compaction_candidate,
            enforce_target=(
                trigger == "auto" or self._compaction_policy.compact_budget is None
            ),
        )
        return await service.compact(
            self._history,
            self._summary,
            self._summary_entry_id,
            self._prev_details,
            target_budget=target_budget,
        )

    def _publish_compaction_result(
        self,
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot | None,
        target_budget: int,
        result: Any,
    ) -> bool:
        finished = self._compaction_finished_metadata(trigger, snapshot, target_budget, result)
        if result.status == "skipped":
            self._remember_compaction_fingerprint(trigger, snapshot)
            self._emit_compaction_finished({"success": True, **finished})
            return False
        self._summary = result.summary
        self._summary_entry_id = result.summary_entry_id
        self._prev_details = result.details
        self._history = result.kept_history
        self._last_compaction_failure_fingerprint = None
        self._remember_compaction_fingerprint(trigger, snapshot)
        self._emit_compaction_finished({"success": True, **finished})
        return True

    def _remember_compaction_fingerprint(
        self,
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot | None,
    ) -> None:
        if trigger == "auto" and snapshot is not None:
            self._last_compaction_fingerprint = self._compaction_fingerprint(snapshot)

    def _emit_compaction_finished(self, metadata: dict[str, Any]) -> None:
        self._emit(
            AgentEvent(EventType.COMPACTION_FINISHED, metadata=metadata),
            self._runtime.active_run_id,
        )

    def _handle_compaction_cancelled(
        self,
        metadata: dict[str, Any],
        persistence_started: bool,
    ) -> bool:
        if persistence_started:
            self._emit_compaction_finished(
                {
                    **metadata,
                    "success": False,
                    "status": "persistence_uncertain",
                    "error_code": "persistence_uncertain",
                    "reason_code": "persistence_uncertain",
                    "error_message": "压缩记录持久化结果不确定",
                }
            )
            return True
        self._emit_compaction_finished(
            {
                **metadata,
                "success": False,
                "status": "cancelled",
                "reason_code": "cancelled",
            }
        )
        return False

    def _handle_compaction_error(
        self,
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot | None,
        metadata: dict[str, Any],
        exc: Exception,
    ) -> None:
        if trigger == "auto" and snapshot is not None:
            self._last_compaction_failure_fingerprint = self._compaction_fingerprint(snapshot)
        if isinstance(exc, PersistenceUncertainError):
            error_code = "persistence_uncertain"
        elif isinstance(exc, ValueError):
            error_code = "compaction_unavailable"
        else:
            error_code = "compaction_failed"
        self._emit_compaction_finished(
            {
                **metadata,
                "success": False,
                "status": (
                    "persistence_uncertain"
                    if error_code == "persistence_uncertain"
                    else "failed"
                ),
                "error_code": error_code,
                "reason_code": error_code,
                "error_message": str(exc),
            }
        )
        self._emit(
            AgentEvent(
                EventType.ERROR,
                payload=str(exc),
                metadata={
                    "error_code": error_code,
                    "error_message": str(exc),
                    "phase": "compaction",
                    "post_commit": trigger == "auto",
                },
            ),
            self._runtime.active_run_id,
        )

    async def _maybe_auto_compact(self) -> bool:
        """Recompute the next request budget before considering auto compaction."""
        if not self._summarizer or not self._compaction_policy.enabled:
            return False
        snapshot = await self._next_request_budget()
        self._pending_compaction_budget = snapshot
        try:
            if not self._should_auto_compact():
                return False
            return await self.compact(trigger="auto")
        finally:
            self._pending_compaction_budget = None

    def _should_auto_compact(self) -> bool:
        snapshot = self._pending_compaction_budget or self._budget_state.latest_estimate
        return bool(
            self._summarizer
            and snapshot is not None
            and decide_auto_compaction(snapshot, self._compaction_policy).should_compact
        )

    def _on_internal_event(self, event: AgentEvent) -> None:
        if event.type == EventType.CONTEXT_BUDGET:
            if isinstance(event.payload, ContextBudgetSnapshot):
                self._budget_state.record_estimate(
                    event.payload,
                    model_id=getattr(self, "model_id", None),
                )
        elif event.type == EventType.CONTEXT_PREFLIGHT:
            self._budget_state.record_preflight(event.payload)
        elif event.type == EventType.USAGE:
            payload: dict[str, Any] = event.payload or {}
            self._budget_state.record_actual_usage(payload)
            tokens = payload.get("input_tokens")
            if tokens:
                self._last_input_tokens = int(tokens)
            self._runtime.record_usage(payload)
        elif event.type == EventType.COMPACTION_FINISHED:
            self._budget_state.record_compaction(dict(event.metadata or {}))
        elif event.type == EventType.TOOL_RESULT:
            self._budget_state.record_tool_result(dict(event.metadata or {}))
        elif event.type == EventType.ERROR:
            self._budget_state.record_failure(dict(event.metadata or {}))


__all__ = ["SessionCompactionMixin"]
