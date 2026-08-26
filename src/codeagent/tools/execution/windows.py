"""Windows Git Bash 进程策略。"""

from __future__ import annotations

import subprocess
from typing import Any

__all__ = ["WindowsProcessBackend"]


class WindowsProcessBackend:
    """为非交互式 Git Bash 创建进程组并尽力清理整棵进程树。"""

    def spawn_kwargs(self, cwd: str, env: dict[str, str]) -> dict[str, Any]:
        return {
            "cwd": cwd,
            "env": env,
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW,
        }

    def async_spawn_kwargs(self, cwd: str, env: dict[str, str]) -> dict[str, Any]:
        return self.spawn_kwargs(cwd, env)

    def kill_tree(self, pid: int) -> bool:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        # MSYS 子进程可能被重新挂载到运行时进程树之外，不能证明全树已停止。
        return False
