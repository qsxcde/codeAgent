"""Linux/macOS 共用的 POSIX 进程组策略。"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any

__all__ = ["PosixProcessBackend"]


class PosixProcessBackend:
    """使用独立 session 和进程组管理 POSIX 子进程。"""

    def spawn_kwargs(self, cwd: str, env: dict[str, str]) -> dict[str, Any]:
        return {"cwd": cwd, "env": env, "start_new_session": True}

    def kill_tree(self, pid: int) -> bool:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return True
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
                return True
            except ProcessLookupError:
                return True

    def async_spawn_kwargs(self, cwd: str, env: dict[str, str]) -> dict[str, Any]:
        return self.spawn_kwargs(cwd, env)
