"""Bounded budget policy for one application-layer Subagent delegation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from codeagent.core.contracts.subagents import SubagentBudget

DEFAULT_MAX_CHILDREN_PER_RUN = 4
DEFAULT_MAX_TURNS = 8
DEFAULT_MAX_TOOL_CALLS = 32
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_OUTPUT_CHARS = 8_000

MAX_MAX_TURNS = 16
MAX_MAX_TOOL_CALLS = 64
MAX_TIMEOUT_SECONDS = 300.0
MAX_MAX_OUTPUT_CHARS = 16_000

_BUDGET_FIELDS = frozenset(
    {"max_turns", "max_tool_calls", "timeout_seconds", "max_output_chars"}
)


@dataclass(frozen=True, slots=True)
class EffectiveSubagentBudget:
    """A fully materialized budget safe to use by the runner."""

    max_turns: int
    max_tool_calls: int
    timeout_seconds: float
    max_output_chars: int


def parse_budget(value: object) -> SubagentBudget:
    """Parse the model-facing budget object without silently accepting fields."""
    if value is None:
        return SubagentBudget()
    if not isinstance(value, Mapping):
        raise ValueError("delegate.budget 必须是对象")
    unknown = set(value) - _BUDGET_FIELDS
    if unknown:
        names = ", ".join(sorted(str(item) for item in unknown))
        raise ValueError(f"delegate.budget 包含未知字段: {names}")
    values = {}
    for name in _BUDGET_FIELDS:
        if name not in value:
            continue
        if value[name] is None:
            raise ValueError(f"delegate.budget.{name} 不能为 null")
        values[name] = value[name]
    try:
        budget = SubagentBudget(**values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"delegate.budget 无效: {exc}") from exc
    effective_budget(budget)
    return budget


def effective_budget(budget: SubagentBudget) -> EffectiveSubagentBudget:
    """Fill defaults and enforce the hard application safety caps."""
    if not isinstance(budget, SubagentBudget):
        raise ValueError("budget 必须是 SubagentBudget")
    max_turns = budget.max_turns or DEFAULT_MAX_TURNS
    max_tool_calls = budget.max_tool_calls or DEFAULT_MAX_TOOL_CALLS
    timeout_seconds = float(budget.timeout_seconds or DEFAULT_TIMEOUT_SECONDS)
    max_output_chars = budget.max_output_chars or DEFAULT_MAX_OUTPUT_CHARS
    limits = (
        ("max_turns", max_turns, MAX_MAX_TURNS),
        ("max_tool_calls", max_tool_calls, MAX_MAX_TOOL_CALLS),
        ("timeout_seconds", timeout_seconds, MAX_TIMEOUT_SECONDS),
        ("max_output_chars", max_output_chars, MAX_MAX_OUTPUT_CHARS),
    )
    for name, value, maximum in limits:
        if value > maximum:
            raise ValueError(f"{name} 不得超过 {maximum}")
    return EffectiveSubagentBudget(
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )


__all__ = [
    "DEFAULT_MAX_CHILDREN_PER_RUN",
    "DEFAULT_MAX_OUTPUT_CHARS",
    "DEFAULT_MAX_TOOL_CALLS",
    "DEFAULT_MAX_TURNS",
    "DEFAULT_TIMEOUT_SECONDS",
    "EffectiveSubagentBudget",
    "MAX_MAX_OUTPUT_CHARS",
    "MAX_MAX_TOOL_CALLS",
    "MAX_MAX_TURNS",
    "MAX_TIMEOUT_SECONDS",
    "effective_budget",
    "parse_budget",
]
