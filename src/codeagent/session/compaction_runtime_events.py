"""Event metadata and skipped-result projection for session compaction."""

from __future__ import annotations

from typing import Any, Literal

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.contracts.events import AgentEvent, EventType


CompactionTrigger = Literal["manual", "auto"]


class SessionCompactionEventsMixin:
    """Publish stable diagnostics without owning compaction state changes."""

    @staticmethod
    def _compaction_started_metadata(
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot | None,
        target_budget: int,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "trigger": trigger,
            "reason": reason,
            "input_tokens": snapshot.input_tokens if snapshot else None,
            "input_budget": snapshot.input_budget if snapshot else None,
            "headroom": snapshot.headroom if snapshot else None,
            "target_budget": target_budget,
        }

    @staticmethod
    def _compaction_finished_metadata(
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot | None,
        target_budget: int,
        result: Any,
    ) -> dict[str, Any]:
        return {
            "trigger": trigger,
            "status": result.status,
            "reason_code": result.reason_code,
            "reason": result.reason,
            "before_input_tokens": snapshot.input_tokens if snapshot else None,
            "after_input_tokens": result.after_input_tokens,
            "input_budget": snapshot.input_budget if snapshot else None,
            "target_budget": target_budget,
            "summarized_turns": result.summarized_turns,
            "kept_turns": result.kept_turns,
            "summary_entry_id": result.summary_entry_id,
            "summarized_entry_ids": list(result.summarized_entry_ids),
            "kept_entry_ids": list(result.kept_entry_ids),
        }

    def _emit_skipped_compaction(
        self,
        trigger: CompactionTrigger,
        snapshot: ContextBudgetSnapshot,
        target_budget: int,
        reason_code: str,
        reason: str,
    ) -> bool:
        metadata = self._compaction_started_metadata(trigger, snapshot, target_budget, reason)
        self._emit(
            AgentEvent(EventType.COMPACTION_STARTED, metadata=metadata),
            self._runtime.active_run_id,
        )
        self._emit(
            AgentEvent(
                EventType.COMPACTION_FINISHED,
                metadata={
                    **metadata,
                    "success": True,
                    "status": "skipped",
                    "compacted": False,
                    "reason_code": reason_code,
                    "reason": reason,
                },
            ),
            self._runtime.active_run_id,
        )
        return False


__all__ = ["CompactionTrigger", "SessionCompactionEventsMixin"]
