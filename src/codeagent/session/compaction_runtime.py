"""Stateful compaction methods for ``AgentSession``."""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context.preflight import ContextPreflightResult
from codeagent.session.compaction.service import CompactionService
from codeagent.session.constants import COMPACTION_RESERVE_TOKENS


class SessionCompactionMixin:
    """Coordinate compaction without owning the session facade constructor."""

    async def compact(self) -> bool:
        self._emit(
            AgentEvent(EventType.COMPACTION_STARTED),
            self._runtime.active_run_id,
        )
        try:
            service = CompactionService(
                self._summarizer,
                self._compact_budget,
                self._persistence.append_compaction_async,
            )
            result = await service.compact(
                self._history,
                self._summary,
                self._summary_entry_id,
                self._prev_details,
            )
            if result is None:
                self._emit(
                    AgentEvent(
                        EventType.COMPACTION_FINISHED,
                        metadata={"success": True, "compacted": False},
                    ),
                    self._runtime.active_run_id,
                )
                return False
            self._summary = result.summary
            self._summary_entry_id = result.summary_entry_id
            self._prev_details = result.details
            self._history = result.kept_history
            self._emit(
                AgentEvent(
                    EventType.COMPACTION_FINISHED,
                    metadata={"success": True, "compacted": True},
                ),
                self._runtime.active_run_id,
            )
            return True
        except Exception as exc:
            self._emit(
                AgentEvent(
                    EventType.COMPACTION_FINISHED,
                    metadata={
                        "success": False,
                        "error_code": (
                            "compaction_unavailable"
                            if isinstance(exc, ValueError)
                            else "compaction_failed"
                        ),
                        "error_message": str(exc),
                    },
                ),
                self._runtime.active_run_id,
            )
            raise

    def _should_auto_compact(self) -> bool:
        return bool(
            self._summarizer
            and self._last_input_tokens
            and self._last_input_tokens > self._context_window - COMPACTION_RESERVE_TOKENS
        )

    def _on_internal_event(self, event: AgentEvent) -> None:
        if event.type == EventType.CONTEXT_BUDGET:
            if isinstance(event.payload, ContextBudgetSnapshot):
                self._budget_state.record_estimate(event.payload)
        elif event.type == EventType.CONTEXT_PREFLIGHT:
            if isinstance(event.payload, ContextPreflightResult):
                self._budget_state.record_preflight(event.payload)
        elif event.type == EventType.USAGE:
            payload: dict[str, Any] = event.payload or {}
            self._budget_state.record_actual_usage(payload)
            tokens = payload.get("input_tokens")
            if tokens:
                self._last_input_tokens = int(tokens)
            self._runtime.record_usage(payload)


__all__ = ["SessionCompactionMixin"]
