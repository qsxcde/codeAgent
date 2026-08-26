"""Session persistence locking helpers."""

from __future__ import annotations

import threading
from pathlib import Path

_path_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def path_lock(path: str | Path) -> threading.RLock:
    """Return the process-local reentrant lock associated with ``path``."""
    key = str(path)
    lock = _path_locks.get(key)
    if lock is None:
        with _guard:
            lock = _path_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                _path_locks[key] = lock
    return lock


__all__ = ["path_lock"]
