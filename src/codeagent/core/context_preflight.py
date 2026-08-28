"""Provider-neutral context budget preflight decisions.

The preflight step deliberately contains no compaction, truncation, retry, or
provider calls. It turns the final request budget snapshot into a stable
decision that the runtime and session layers can observe and act on.

The contract is specified by the OpenSpec change
``context-budget-preflight`` and builds on ``context-budget-contract``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from codeagent.core.context_budget import ContextBudgetSnapshot

PreflightStatus = Literal["safe", "near_limit", "over_limit", "uncertain"]


@dataclass(frozen=True)
class ContextPreflightConfig:
    """Warning boundary for one model request."""

    warning_headroom_tokens: int | None = 2_048
    warning_headroom_ratio: float | None = None

    def __post_init__(self) -> None:
        tokens = self.warning_headroom_tokens
        ratio = self.warning_headroom_ratio
        if tokens is not None and ratio is not None:
            raise ValueError(
                "configure either warning_headroom_tokens or "
                "warning_headroom_ratio, not both"
            )
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError("warning_headroom_tokens must be a non-negative integer")
        if ratio is not None and (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not math.isfinite(float(ratio))
            or not 0 < float(ratio) <= 1
        ):
            raise ValueError("warning_headroom_ratio must be finite and in (0, 1]")

    def warning_boundary(self, input_budget: int) -> int | None:
        """Return the warning headroom in tokens for an input budget."""

        if self.warning_headroom_tokens is not None:
            return self.warning_headroom_tokens
        if self.warning_headroom_ratio is not None:
            return int(input_budget * float(self.warning_headroom_ratio))
        return None


@dataclass(frozen=True)
class ContextPreflightResult:
    """Stable result of a request preflight."""

    status: PreflightStatus
    allowed: bool
    reason: str
    snapshot: ContextBudgetSnapshot
    warning_headroom_tokens: int | None = None
    warning_headroom_ratio: float | None = None
    warning_boundary: int | None = None

    @property
    def budget(self) -> ContextBudgetSnapshot:
        """Alias for consumers that call the snapshot a budget."""

        return self.snapshot

    @property
    def input_tokens(self) -> int:
        return self.snapshot.input_tokens

    @property
    def input_budget(self) -> int:
        return self.snapshot.input_budget

    @property
    def headroom(self) -> int:
        return self.snapshot.headroom

    @property
    def window_source(self) -> str:
        return self.snapshot.window_source


def evaluate_context_preflight(
    snapshot: ContextBudgetSnapshot,
    config: ContextPreflightConfig,
    *,
    uncertain_budget_policy: str = "allow",
) -> ContextPreflightResult:
    """Evaluate a budget snapshot without mutating it or performing I/O."""

    if uncertain_budget_policy not in {"allow", "fail"}:
        raise ValueError("uncertain_budget_policy must be 'allow' or 'fail'")

    boundary = config.warning_boundary(snapshot.input_budget)
    if snapshot.status == "uncertain":
        allowed = uncertain_budget_policy == "allow"
        action = "allowed" if allowed else "blocked"
        return ContextPreflightResult(
            status="uncertain",
            allowed=allowed,
            reason=(
                f"context window is uncertain; request {action} by "
                f"uncertain_budget_policy='{uncertain_budget_policy}'"
            ),
            snapshot=snapshot,
            warning_headroom_tokens=config.warning_headroom_tokens,
            warning_headroom_ratio=config.warning_headroom_ratio,
            warning_boundary=boundary,
        )

    if snapshot.headroom < 0:
        return ContextPreflightResult(
            status="over_limit",
            allowed=False,
            reason=(
                "estimated input exceeds the available context budget "
                f"by {-snapshot.headroom} tokens"
            ),
            snapshot=snapshot,
            warning_headroom_tokens=config.warning_headroom_tokens,
            warning_headroom_ratio=config.warning_headroom_ratio,
            warning_boundary=boundary,
        )

    near_limit = boundary is not None and snapshot.headroom <= boundary
    status: PreflightStatus = "near_limit" if near_limit else "safe"
    reason = (
        f"estimated input leaves {snapshot.headroom} tokens of headroom"
        if near_limit
        else "estimated input fits the available context budget"
    )
    return ContextPreflightResult(
        status=status,
        allowed=True,
        reason=reason,
        snapshot=snapshot,
        warning_headroom_tokens=config.warning_headroom_tokens,
        warning_headroom_ratio=config.warning_headroom_ratio,
        warning_boundary=boundary,
    )


__all__ = [
    "ContextPreflightConfig",
    "ContextPreflightResult",
    "PreflightStatus",
    "evaluate_context_preflight",
]
