"""Provider-agnostic boundary for compaction summary generation."""

from __future__ import annotations

from typing import Protocol

from codeagent.core.messages import Message


class Summarizer(Protocol):
    async def summarize(
        self, messages: list[Message], previous_summary: str | None
    ) -> str: ...


__all__ = ["Summarizer"]
