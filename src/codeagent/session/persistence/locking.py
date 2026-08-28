"""Cross-process locks for session persistence files.

The in-process lock is still needed because a session store re-enters the
lock while updating the derived index. The sidecar lock adds the missing
process boundary so two codeagent processes cannot append or roll back the
same JSONL file at the same time.
"""

from __future__ import annotations

import errno
import os
import threading
import time
from pathlib import Path

_path_locks: dict[str, "PathLock"] = {}
_guard = threading.Lock()
_DEFAULT_TIMEOUT = 30.0
_RETRY_DELAY = 0.02


class PathLock:
    """A re-entrant thread lock backed by an OS advisory file lock."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        self._owner: int | None = None
        self._depth = 0
        self._fd: int | None = None

    def __enter__(self) -> "PathLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()

    def acquire(self, timeout: float | None = None) -> bool:
        """Acquire the process and thread lock, waiting at most ``timeout``."""
        self._thread_lock.acquire()
        thread_id = threading.get_ident()
        if self._owner == thread_id:
            self._depth += 1
            return True
        try:
            self._acquire_os(timeout if timeout is not None else _DEFAULT_TIMEOUT)
        except BaseException:
            self._thread_lock.release()
            raise
        self._owner = thread_id
        self._depth = 1
        return True

    def release(self) -> None:
        if self._owner != threading.get_ident():
            raise RuntimeError("cannot release an unowned session path lock")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            try:
                self._release_os()
            finally:
                self._thread_lock.release()
            return
        self._thread_lock.release()

    def _acquire_os(self, timeout: float) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
            else:
                import fcntl

            deadline = time.monotonic() + max(0.0, timeout)
            while True:
                try:
                    if os.name == "nt":
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    return
                except OSError as exc:
                    retryable = exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                    if not retryable or time.monotonic() >= deadline:
                        raise TimeoutError(f"获取会话锁超时: {self._path}") from exc
                    time.sleep(_RETRY_DELAY)
        except BaseException:
            os.close(fd)
            raise

    def _release_os(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def path_lock(path: str | Path) -> PathLock:
    """Return the stable, re-entrant lock associated with ``path``."""
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    lock = _path_locks.get(key)
    if lock is None:
        with _guard:
            lock = _path_locks.get(key)
            if lock is None:
                lock = PathLock(key)
                _path_locks[key] = lock
    return lock


__all__ = ["PathLock", "path_lock"]
