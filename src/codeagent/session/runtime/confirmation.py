"""Confirmation request coordination for session tools."""

from __future__ import annotations

import asyncio


class ConfirmationCoordinator:
    """Match approval responses to the request currently being awaited."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    async def wait(self, request_id: str) -> bool:
        """Wait for the requested response, preserving sequential semantics."""
        while True:
            got_id, approved = await self.queue.get()
            if got_id == request_id:
                return approved

    def respond(self, request_id: str, approved: bool) -> None:
        self.queue.put_nowait((request_id, approved))

    def clear(self) -> None:
        """Discard responses that cannot belong to a future run."""
        while not self.queue.empty():
            self.queue.get_nowait()
