"""TUI 流式事件的有界、顺序保持缓冲。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from codeagent.core.contracts.events import AgentEvent, EventType

__all__ = ["TuiEventBuffer"]


class TuiEventBuffer:
    """合并相邻展示增量，同时在结构事件前保持严格顺序。"""

    _MERGEABLE = {EventType.THINKING_DELTA, EventType.TEXT_DELTA}
    MAX_PENDING_CHARS = 4096

    def __init__(self, apply: Callable[[AgentEvent], None]) -> None:
        self._apply = apply
        self._pending: AgentEvent | None = None
        self._pending_parts: list[str] = []
        self._pending_chars = 0
        self._max_pending_chars = 0
        self._flush_count = 0

    @property
    def pending_chars(self) -> int:
        """Return the number of buffered characters awaiting model apply."""
        return self._pending_chars

    @property
    def max_pending_chars(self) -> int:
        """Return the largest buffered batch observed by this buffer."""
        return self._max_pending_chars

    @property
    def flush_count(self) -> int:
        """Return the number of buffered batches applied to the model."""
        return self._flush_count

    def push(self, event: AgentEvent) -> None:
        if event.type not in self._MERGEABLE:
            self.flush()
            self._apply(event)
            return
        payload = str(event.payload or "")
        if self._pending is None:
            self._start(event, payload)
        elif self._pending.type != event.type:
            self.flush()
            self._start(event, payload)
        elif self._pending_chars + len(payload) > self.MAX_PENDING_CHARS:
            self.flush()
            self._start(event, payload)
        else:
            self._pending_parts.append(payload)
            self._pending_chars += len(payload)
            self._pending = replace(self._pending, metadata=dict(event.metadata or {}))
        self._max_pending_chars = max(self._max_pending_chars, self._pending_chars)
        if self._pending_chars >= self.MAX_PENDING_CHARS:
            self.flush()

    def _start(self, event: AgentEvent, payload: str) -> None:
        """Start a bounded batch, splitting an oversized single delta."""
        if len(payload) > self.MAX_PENDING_CHARS:
            for start in range(0, len(payload), self.MAX_PENDING_CHARS):
                chunk = payload[start : start + self.MAX_PENDING_CHARS]
                self._apply(replace(event, payload=chunk, metadata=dict(event.metadata or {})))
                self._flush_count += 1
            return
        self._pending = replace(event, payload="", metadata=dict(event.metadata or {}))
        self._pending_parts = [payload]
        self._pending_chars = len(payload)

    def _clear(self) -> None:
        self._pending = None
        self._pending_parts = []
        self._pending_chars = 0

    def flush(self) -> None:
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._apply(replace(pending, payload="".join(self._pending_parts)))
            self._flush_count += 1
        self._clear()
