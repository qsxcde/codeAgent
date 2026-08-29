"""State transitions for per-tool TUI aggregation."""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.tool_status import ToolLifecycleStatus

__all__ = ["is_terminal", "normalize_status", "transition_status"]


def normalize_status(value: Any, default: str = ToolLifecycleStatus.RUNNING) -> str:
    """Normalize legacy status values without parsing result text."""
    try:
        return ToolLifecycleStatus.normalize(value or default)
    except ValueError:
        return str(value or default)


def is_terminal(status: str) -> bool:
    """Return whether a lifecycle status is final."""
    return status in ToolLifecycleStatus.TERMINAL


def transition_status(
    counts: dict[str, int],
    states: dict[str, str],
    call_id: str,
    next_status: str,
) -> tuple[dict[str, int], dict[str, str], bool]:
    """Apply one idempotent status transition and return whether it changed."""
    if not call_id:
        return counts, states, False
    previous = states.get(call_id)
    if previous == next_status or (previous is not None and is_terminal(previous)):
        return counts, states, False
    updated_counts = dict(counts)
    if previous is not None:
        updated_counts[previous] = max(0, updated_counts.get(previous, 0) - 1)
    updated_counts[next_status] = updated_counts.get(next_status, 0) + 1
    updated_states = dict(states)
    updated_states[call_id] = next_status
    return updated_counts, updated_states, True
