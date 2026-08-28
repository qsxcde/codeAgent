"""Compaction estimation and cut-point policy."""

from __future__ import annotations

import json

from codeagent.core.messages import Message

DEFAULT_BUDGET_TOKENS = 20_000


def estimate_tokens(message: Message) -> int:
    """Estimate message tokens using the existing conservative heuristic."""
    chars = len(message.content)
    for call in message.tool_calls:
        chars += len(call.name) + len(json.dumps(call.args, ensure_ascii=False))
    return max(1, chars // 4)


def find_cut_point(
    messages: list[Message], budget: int = DEFAULT_BUDGET_TOKENS
) -> int:
    """Return the first retained message index at a complete-turn boundary."""
    budget = max(1, budget)
    index = len(messages)
    total = 0
    i = len(messages) - 1
    while i >= 0:
        turn_start = i
        while turn_start >= 0 and messages[turn_start].role != "user":
            turn_start -= 1
        if turn_start < 0:
            break
        turn_tokens = sum(estimate_tokens(m) for m in messages[turn_start : i + 1])
        if total > 0 and total + turn_tokens > budget:
            break
        total += turn_tokens
        index = turn_start
        i = turn_start - 1
    # A history without a user boundary (or a single oversized turn) has no
    # safe cut point. Returning zero makes callers keep the full history
    # instead of treating ``len(messages)`` as an empty retained window.
    return 0 if index == len(messages) else index
