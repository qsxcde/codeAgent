"""Typed errors for persistence outcomes that cannot be confirmed."""

from __future__ import annotations

import asyncio


class PersistenceUncertainError(RuntimeError):
    """A persistence operation may have partially completed."""


class PersistenceCancellationUncertainError(asyncio.CancelledError):
    """Cancellation arrived while a persistence result was still uncertain."""


__all__ = [
    "PersistenceCancellationUncertainError",
    "PersistenceUncertainError",
]
