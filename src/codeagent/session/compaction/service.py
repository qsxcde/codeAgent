"""Session-facing compaction service.

The policy module chooses a safe cut point; this service owns the stateful
operation of summarizing that window and appending one compaction record. The
session facade remains responsible for events and publishing the new state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import inspect
from dataclasses import dataclass, field
from typing import Literal

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.contracts.messages import Message
from codeagent.session.compaction.details import extract_file_ops
from codeagent.session.compaction.policy import (
    CompactionPlan,
    estimate_tokens,
    plan_compaction,
)
from codeagent.session.compaction.summarizer import Summarizer
from codeagent.session.persistence.models import CompactionEntry

CandidateBudget = Callable[
    [str, list[Message]],
    ContextBudgetSnapshot | Awaitable[ContextBudgetSnapshot],
]
CompactionStatus = Literal["compacted", "skipped"]


@dataclass(frozen=True)
class CompactionResult:
    """State produced after one compaction attempt."""

    kept_history: list[Message] = field(default_factory=list)
    summary: str | None = None
    summary_entry_id: str | None = None
    details: dict[str, list[str]] = field(default_factory=dict)
    status: CompactionStatus = "compacted"
    reason_code: str = "compacted"
    reason: str = ""
    before_input_tokens: int | None = None
    after_input_tokens: int | None = None
    target_budget: int | None = None
    summarized_turns: int = 0
    kept_turns: int = 0
    summarized_entry_ids: tuple[str, ...] = ()
    kept_entry_ids: tuple[str, ...] = ()


class CompactionService:
    """Perform one compaction without owning session events or history state."""

    def __init__(
        self,
        summarizer: Summarizer | None,
        budget: int,
        append_entry: Callable[[CompactionEntry], Awaitable[str]],
        *,
        min_recent_turns: int = 1,
        candidate_budget: CandidateBudget | None = None,
        enforce_target: bool = True,
    ) -> None:
        self._summarizer = summarizer
        self._budget = budget
        self._append_entry = append_entry
        self._min_recent_turns = min_recent_turns
        self._candidate_budget = candidate_budget
        self._enforce_target = enforce_target
        self._last_plan: CompactionPlan | None = None

    @property
    def last_plan(self) -> CompactionPlan | None:
        """Return the most recent pure selection result for diagnostics."""
        return self._last_plan

    async def compact(
        self,
        history: list[Message],
        previous_summary: str | None,
        previous_summary_entry_id: str | None,
        previous_details: dict[str, list[str]],
        *,
        target_budget: int | None = None,
    ) -> CompactionResult:
        """Summarize and persist a safe prefix, returning a structured result."""
        if self._summarizer is None:
            raise ValueError("压缩不可用:未注入 Summarizer")
        target = self._budget if target_budget is None else target_budget
        plan = plan_compaction(
            history,
            target,
            min_recent_turns=self._min_recent_turns,
        )
        self._last_plan = plan
        if plan.reason_code != "ready":
            return CompactionResult(
                status="skipped",
                reason_code=plan.reason_code,
                reason=plan.reason,
                target_budget=target,
                summarized_turns=plan.summarized_turns,
                kept_turns=plan.kept_turns,
            )

        window = history[: plan.cut_point]
        kept = history[plan.cut_point :]
        summary = await self._summarizer.summarize(window, previous_summary)
        candidate = await self._estimate_candidate(summary, kept)
        if candidate is not None and (
            candidate.headroom < 0
            or (self._enforce_target and candidate.input_tokens > target)
        ):
            return CompactionResult(
                status="skipped",
                reason_code="summary_too_large",
                reason="summary and retained history exceed the compaction target",
                target_budget=target,
                before_input_tokens=None,
                after_input_tokens=candidate.input_tokens,
                summarized_turns=plan.summarized_turns,
                kept_turns=plan.kept_turns,
            )
        return await self._persist_compaction(
            window,
            kept,
            summary,
            candidate,
            previous_details,
            previous_summary_entry_id,
            history[-1].id if history else None,
            target,
            plan,
        )

    async def _persist_compaction(
        self,
        window: list[Message],
        kept: list[Message],
        summary: str,
        candidate: ContextBudgetSnapshot | None,
        previous_details: dict[str, list[str]],
        previous_summary_entry_id: str | None,
        last_history_id: str | None,
        target: int,
        plan: CompactionPlan,
    ) -> CompactionResult:
        fresh = extract_file_ops(window)
        details = {
            "readFiles": list(
                dict.fromkeys(previous_details.get("readFiles", []) + fresh["readFiles"])
            ),
            "modifiedFiles": list(
                dict.fromkeys(
                    previous_details.get("modifiedFiles", []) + fresh["modifiedFiles"]
                )
            ),
        }
        parent_id = previous_summary_entry_id or last_history_id
        entry = CompactionEntry(
            summary=summary,
            details=details,
            parent_id=parent_id,
            first_kept_entry_id=kept[0].id if kept else "",
        )
        entry_id = await self._append_entry(entry)
        return CompactionResult(
            kept_history=kept,
            summary=summary,
            summary_entry_id=entry_id,
            details=details,
            status="compacted",
            reason_code="compacted",
            reason="compaction persisted successfully",
            after_input_tokens=candidate.input_tokens if candidate is not None else None,
            target_budget=target,
            summarized_turns=plan.summarized_turns,
            kept_turns=plan.kept_turns,
            summarized_entry_ids=tuple(message.id for message in window),
            kept_entry_ids=tuple(message.id for message in kept),
        )

    async def _estimate_candidate(
        self,
        summary: str,
        kept: list[Message],
    ) -> ContextBudgetSnapshot | None:
        if self._candidate_budget is not None:
            result = self._candidate_budget(summary, list(kept))
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, ContextBudgetSnapshot):
                raise TypeError("candidate_budget must return ContextBudgetSnapshot")
            return result
        summary_message = Message(role="user", content=summary)
        estimated = estimate_tokens(summary_message) + sum(
            estimate_tokens(message) for message in kept
        )
        return ContextBudgetSnapshot(
            context_window=max(self._budget, estimated),
            output_reserve=0,
            reserve_tokens=0,
            input_budget=self._budget,
            system_prompt_tokens=0,
            tool_definitions_tokens=0,
            conversation_tokens=estimated,
            tool_result_tokens=0,
            input_tokens=estimated,
            headroom=self._budget - estimated,
            status="estimate",
            window_source="compaction",
        )


__all__ = ["CompactionResult", "CompactionService"]
