"""Small async adaptation helpers shared by core collaborators."""

from __future__ import annotations

from typing import Any


async def await_if_needed(value: Any) -> Any:
    """Await a value when an injected port returns an awaitable."""
    if hasattr(value, "__await__"):
        return await value
    return value


__all__ = ["await_if_needed"]
