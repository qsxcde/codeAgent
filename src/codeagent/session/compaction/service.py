"""Session-facing compaction service.

The policy module chooses a safe cut point; this service owns the stateful
operation of summarizing that window and appending one compaction record. The
session facade remains responsible for events and publishing the new state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from codeagent.core.contracts.messages import Message
from codeagent.session.compaction.details import extract_file_ops
from codeagent.session.compaction.policy import find_cut_point
from codeagent.session.persistence.models import CompactionEntry


@dataclass(frozen=True)
class CompactionResult:
    """State produced after one successfully persisted compaction."""

    kept_history: list[Message]
    summary: str
    summary_entry_id: str
    details: dict[str, list[str]]


class CompactionService:
    """Perform one compaction without owning session events or history state."""

    def __init__(
        self,
        summarizer: Any,
        budget: int,
        append_entry: Callable[[CompactionEntry], str],
    ) -> None:
        self._summarizer = summarizer
        self._budget = budget
        self._append_entry = append_entry

    async def compact(
        self,
        history: list[Message],
        previous_summary: str | None,
        previous_summary_entry_id: str | None,
        previous_details: dict[str, list[str]],
    ) -> CompactionResult | None:
        """Summarize and persist a safe prefix, or return ``None`` if skipped."""
        if self._summarizer is None:
            raise ValueError("压缩不可用:未注入 Summarizer")
        cut = find_cut_point(history, self._budget)
        if cut <= 0 or cut >= len(history):
            return None

        window = history[:cut]
        kept = history[cut:]
        summary = await self._summarizer.summarize(window, previous_summary)
        fresh = extract_file_ops(window)
        details = {
            "readFiles": list(
                dict.fromkeys(previous_details.get("readFiles", []) + fresh["readFiles"])
            ),
            "modifiedFiles": list(
                dict.fromkeys(
                    previous_details.get("modifiedFiles", [])
                    + fresh["modifiedFiles"]
                )
            ),
        }
        parent_id = previous_summary_entry_id or (history[-1].id if history else None)
        entry = CompactionEntry(
            summary=summary,
            details=details,
            parent_id=parent_id,
            first_kept_entry_id=kept[0].id if kept else "",
        )
        entry_id = self._append_entry(entry)
        return CompactionResult(
            kept_history=kept,
            summary=summary,
            summary_entry_id=entry_id,
            details=details,
        )


__all__ = ["CompactionResult", "CompactionService"]
