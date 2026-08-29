"""状态栏任务计时的独立状态机。"""

from __future__ import annotations

import time
from collections.abc import Callable


class TaskStatusClock:
    """维护任务活动阶段耗时，并在终态锁定最后一个值。"""

    ACTIVE_PHASES = frozenset({"planning", "editing", "verifying", "repairing"})
    TERMINAL_PHASES = frozenset(
        {"completed", "verified", "unverified", "failed", "cancelled", "no_changes"}
    )

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.phase = ""
        self.started_at: float | None = None
        self.elapsed_ms = 0
        self.elapsed_frozen = False

    @property
    def is_active(self) -> bool:
        return self.phase in self.ACTIVE_PHASES and not self.elapsed_frozen

    def update(self, phase: str) -> None:
        """Enter a phase, resetting active phases and freezing terminal phases."""
        now = self._clock()
        if not phase:
            self.started_at = None
            self.elapsed_ms = 0
            self.elapsed_frozen = False
        elif phase != self.phase:
            if phase in self.TERMINAL_PHASES and self.phase in self.ACTIVE_PHASES:
                self._refresh(now)
                self.elapsed_frozen = True
            else:
                self.started_at = now
                self.elapsed_ms = 0
                self.elapsed_frozen = phase in self.TERMINAL_PHASES
        elif phase in self.TERMINAL_PHASES and not self.elapsed_frozen:
            self._refresh(now)
            self.elapsed_frozen = True
        self.phase = phase

    def refresh(self, now: float) -> None:
        """Refresh an active phase without changing task identity."""
        if self.is_active:
            self._refresh(now)

    def _refresh(self, now: float) -> None:
        if self.started_at is None:
            self.started_at = now
        self.elapsed_ms = max(0, round((now - self.started_at) * 1000))
