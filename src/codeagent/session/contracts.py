"""Small protocols owned by the session orchestration layer."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class SessionCloser(Protocol):
    """Composition-root resource closer used during session shutdown."""

    def __call__(self) -> Awaitable[None] | None: ...


__all__ = ["SessionCloser"]
