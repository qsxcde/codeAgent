"""Confirmation request coordination for session tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


class ConfirmationTimeoutError(TimeoutError):
    """Raised when a confirmation request expires before a response."""

    code = "approval_timeout"


@dataclass
class ConfirmationRequest:
    request_id: str
    future: asyncio.Future[bool]
    status: str = "pending"
    timeout_handle: asyncio.TimerHandle | None = None


class ConfirmationCoordinator:
    """Match approval responses to the request currently being awaited."""

    def __init__(self) -> None:
        self._requests: dict[str, ConfirmationRequest] = {}
        # Kept as a read-only compatibility view for old status checks. New
        # request matching is performed exclusively through _requests.
        self.queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    @property
    def active_request_ids(self) -> tuple[str, ...]:
        """Return a stable snapshot of requests still awaiting a response."""
        return tuple(self._requests)

    def register(self, request_id: str, timeout: float | None = None) -> bool:
        """Register one pending request before publishing its UI event."""
        if request_id in self._requests:
            return False
        # Drain only legacy observations; request matching never reads this
        # queue, so stale responses cannot resolve a new request.
        while not self.queue.empty():
            self.queue.get_nowait()
        loop = asyncio.get_running_loop()
        request = ConfirmationRequest(request_id, loop.create_future())
        self._requests[request_id] = request
        if timeout is not None:
            request.timeout_handle = loop.call_later(
                max(0.0, timeout), self._expire, request_id
            )
        return True

    async def wait(self, request_id: str, timeout: float | None = None) -> bool:
        """Wait for a registered request, preserving sequential semantics."""
        if request_id not in self._requests:
            self.register(request_id, timeout)
        request = self._requests[request_id]
        if timeout is not None and request.timeout_handle is None:
            request.timeout_handle = asyncio.get_running_loop().call_later(
                max(0.0, timeout), self._expire, request_id
            )
        try:
            return await request.future
        except asyncio.CancelledError:
            self.cancel(request_id)
            raise
        finally:
            if request.timeout_handle is not None:
                request.timeout_handle.cancel()
            if self._requests.get(request_id) is request:
                self._requests.pop(request_id, None)

    def respond(self, request_id: str, approved: bool) -> bool:
        """Resolve an active request; return False for stale responses."""
        request = self._requests.get(request_id)
        if request is None or request.status != "pending" or request.future.done():
            return False
        request.status = "approved" if approved else "rejected"
        request.future.set_result(approved)
        return True

    def cancel(self, request_id: str) -> bool:
        request = self._requests.get(request_id)
        if request is None or request.status != "pending":
            return False
        request.status = "cancelled"
        request.future.cancel()
        return True

    def cancel_all(self) -> int:
        """Cancel all active requests and wake every waiter."""
        cancelled = 0
        for request_id in list(self._requests):
            cancelled += int(self.cancel(request_id))
        return cancelled

    def _expire(self, request_id: str) -> None:
        request = self._requests.get(request_id)
        if request is None or request.status != "pending" or request.future.done():
            return
        request.status = "expired"
        request.future.set_exception(
            ConfirmationTimeoutError(f"确认请求已超时: {request_id}")
        )

    def clear(self) -> None:
        """Cancel pending requests and discard stale compatibility responses."""
        self.cancel_all()
        while not self.queue.empty():
            self.queue.get_nowait()
