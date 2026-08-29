"""Bounded retry policy for model transport requests."""

from __future__ import annotations

import math
from typing import Any

DEFAULT_MAX_RETRIES = 3
MAX_RETRIES = 5
MAX_RETRY_DELAY = 10.0


def validate_max_retries(value: Any) -> int:
    """Validate the finite retry budget accepted by model clients."""
    if type(value) is not int or not 0 <= value <= MAX_RETRIES:
        raise ValueError(
            f"max_retries must be an integer between 0 and {MAX_RETRIES}"
        )
    return value


def retry_delay(attempt: int, *, retry_after: float | None) -> float:
    """Return a deterministic, bounded delay before the next attempt."""
    if retry_after is not None and math.isfinite(retry_after) and retry_after >= 0:
        return min(retry_after, MAX_RETRY_DELAY)
    return min(2**attempt, MAX_RETRY_DELAY)


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "MAX_RETRIES",
    "MAX_RETRY_DELAY",
    "retry_delay",
    "validate_max_retries",
]
