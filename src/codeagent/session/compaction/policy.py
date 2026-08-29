"""Compaction estimation and cut-point policy."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.contracts.messages import Message

DEFAULT_BUDGET_TOKENS = 20_000


@dataclass(frozen=True)
class CompactionPolicyConfig:
    """Configuration for budget-driven automatic compaction."""

    trigger_ratio: float = 0.8
    target_ratio: float = 0.65
    trigger_headroom_tokens: int | None = 2_048
    min_recent_turns: int = 1
    enabled: bool = True
    compact_budget: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("trigger_ratio", self.trigger_ratio),
            ("target_ratio", self.target_ratio),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 < float(value) <= 1
            ):
                raise ValueError(f"{name} must be finite and in (0, 1]")
        if self.target_ratio >= self.trigger_ratio:
            raise ValueError("target_ratio must be lower than trigger_ratio")
        if self.trigger_headroom_tokens is not None and (
            type(self.trigger_headroom_tokens) is not int
            or self.trigger_headroom_tokens < 0
        ):
            raise ValueError("trigger_headroom_tokens must be a non-negative integer")
        if type(self.min_recent_turns) is not int or self.min_recent_turns < 1:
            raise ValueError("min_recent_turns must be a positive integer")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if self.compact_budget is not None and (
            type(self.compact_budget) is not int or self.compact_budget < 1
        ):
            raise ValueError("compact_budget must be a positive integer")


CompactionReasonCode = Literal[
    "disabled", "threshold", "below_threshold", "budget_unavailable"
]


@dataclass(frozen=True)
class AutoCompactionDecision:
    """Pure automatic-compaction decision for one budget snapshot."""

    should_compact: bool
    target_budget: int
    trigger_budget: int
    reason_code: CompactionReasonCode
    reason: str


CompactionPlanReasonCode = Literal[
    "ready", "no_op", "no_safe_boundary", "oversized_turn"
]


@dataclass(frozen=True)
class CompactionPlan:
    """Pure selection of the history prefix and retained turns."""

    cut_point: int
    target_budget: int
    summarized_turns: int
    kept_turns: int
    reason_code: CompactionPlanReasonCode
    reason: str


def plan_compaction(
    messages: list[Message],
    target_budget: int,
    *,
    min_recent_turns: int = 1,
) -> CompactionPlan:
    """Select a safe complete-turn cut point for a target retained budget."""
    if type(target_budget) is not int or target_budget < 1:
        raise ValueError("target_budget must be a positive integer")
    if type(min_recent_turns) is not int or min_recent_turns < 1:
        raise ValueError("min_recent_turns must be a positive integer")
    if not messages:
        return CompactionPlan(0, target_budget, 0, 0, "no_op", "history is empty")

    starts = [index for index, message in enumerate(messages) if message.role == "user"]
    if not starts:
        return CompactionPlan(
            0,
            target_budget,
            0,
            0,
            "no_safe_boundary",
            "history has no complete user-turn boundary",
        )

    total = 0
    cut_point = len(messages)
    kept_turns = 0
    for position in range(len(starts) - 1, -1, -1):
        start = starts[position]
        end = starts[position + 1] if position + 1 < len(starts) else len(messages)
        turn_tokens = sum(estimate_tokens(message) for message in messages[start:end])
        if kept_turns == 0 and turn_tokens > target_budget:
            return CompactionPlan(
                0,
                target_budget,
                0,
                0,
                "oversized_turn",
                "the most recent required turn exceeds the compaction target",
            )
        if kept_turns >= min_recent_turns and total + turn_tokens > target_budget:
            break
        total += turn_tokens
        cut_point = start
        kept_turns += 1

    if cut_point == 0:
        return CompactionPlan(
            0,
            target_budget,
            0,
            kept_turns,
            "no_op",
            "the complete history fits the compaction target",
        )
    summarized_turns = sum(1 for start in starts if start < cut_point)
    return CompactionPlan(
        cut_point,
        target_budget,
        summarized_turns,
        kept_turns,
        "ready",
        "a complete-turn boundary satisfies the compaction target",
    )


def decide_auto_compaction(
    snapshot: ContextBudgetSnapshot,
    config: CompactionPolicyConfig,
) -> AutoCompactionDecision:
    """Decide whether a snapshot has crossed the automatic trigger."""
    if not config.enabled:
        return AutoCompactionDecision(False, 0, 0, "disabled", "automatic compaction is disabled")
    if snapshot.input_budget < 1:
        return AutoCompactionDecision(
            False,
            0,
            0,
            "budget_unavailable",
            "available input budget is not positive",
        )
    trigger_budget = max(1, math.ceil(snapshot.input_budget * config.trigger_ratio))
    target_budget = max(1, math.floor(snapshot.input_budget * config.target_ratio))
    if config.compact_budget is not None:
        target_budget = min(target_budget, config.compact_budget)
    crossed_ratio = snapshot.input_tokens >= trigger_budget
    crossed_headroom = (
        config.trigger_headroom_tokens is not None
        and snapshot.headroom <= config.trigger_headroom_tokens
    )
    should_compact = crossed_ratio or crossed_headroom
    reason_code: CompactionReasonCode = "threshold" if should_compact else "below_threshold"
    reason = (
        "estimated next request reached the automatic compaction threshold"
        if should_compact
        else "estimated next request remains below the automatic compaction threshold"
    )
    return AutoCompactionDecision(
        should_compact,
        target_budget,
        trigger_budget,
        reason_code,
        reason,
    )


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
