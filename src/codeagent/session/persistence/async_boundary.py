"""Async boundary for synchronous session persistence operations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar


ResultT = TypeVar("ResultT")


class AsyncPersistenceBoundary:
    """Run one synchronous persistence transaction outside the event loop.

    The worker task is shielded so cancelling the session does not abandon an
    atomic append while the backend is still holding its file lock.
    """

    async def run(self, operation: Callable[[], ResultT]) -> ResultT:
        worker = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError as cancelled:
            try:
                await asyncio.shield(worker)
            except BaseException as operation_error:
                raise cancelled from operation_error
            raise cancelled


__all__ = ["AsyncPersistenceBoundary"]
