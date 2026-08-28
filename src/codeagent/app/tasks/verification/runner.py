"""验证命令执行和结果标准化。"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from typing import Any, Awaitable, Callable

from ..modes import is_mutating_command

from .models import TaskStatus, VerificationResult

ExecuteFn = Callable[[str, float], Awaitable[Any] | Any]


class VerificationRunner:
    """运行一条验证命令并标准化结构化结果。"""

    def __init__(
        self,
        cwd: str | os.PathLike[str],
        *,
        execute: ExecuteFn | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.cwd = os.fspath(cwd)
        self.execute = execute
        self.timeout = max(1.0, min(float(timeout), 600.0))

    async def run(
        self,
        command: str,
        *,
        source: str = "explicit",
        timeout: float | None = None,
    ) -> VerificationResult:
        started = time.monotonic()
        limit = self.timeout if timeout is None else max(1.0, min(float(timeout), 600.0))
        if is_mutating_command(command):
            return VerificationResult(
                TaskStatus.UNVERIFIED,
                command=command,
                source=source,
                output_tail="验证命令命中变更型安全策略，未执行",
            )
        try:
            raw = await self._execute(command, limit)
        except asyncio.CancelledError:
            return VerificationResult(
                TaskStatus.CANCELLED,
                command=command,
                source=source,
                duration_ms=round((time.monotonic() - started) * 1000),
                cancelled=True,
            )
        except asyncio.TimeoutError:
            return VerificationResult(
                TaskStatus.FAILED,
                command=command,
                source=source,
                duration_ms=round((time.monotonic() - started) * 1000),
                timed_out=True,
            )
        return self._normalize(raw, command, source, started)

    async def _execute(self, command: str, timeout: float) -> Any:
        if self.execute is not None:
            value = self.execute(command, timeout)
            return await value if inspect.isawaitable(value) else value
        argv = ["cmd.exe", "/d", "/s", "/c", command] if os.name == "nt" else ["/bin/sh", "-lc", command]
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return {
                "status": "timed_out",
                "exit_code": process.returncode,
                "content": "验证命令超时，进程已终止",
                "duration_ms": round(timeout * 1000),
            }
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise
        text = (output or b"").decode("utf-8", errors="replace")
        truncated = len(text) > 12_000
        return {
            "status": "completed" if process.returncode == 0 else "failed",
            "exit_code": process.returncode,
            "content": text[-12_000:] if truncated else text,
            "output_truncated": truncated,
        }

    @staticmethod
    def _normalize(raw: Any, command: str, source: str, started: float) -> VerificationResult:
        if isinstance(raw, dict):
            content = str(raw.get("content") or raw.get("output_tail") or "")
            exit_code = raw.get("exit_code")
            status = str(raw.get("status") or "")
            duration_ms = int(raw.get("duration_ms") or 0)
            truncated = bool(raw.get("output_truncated") or raw.get("truncated_by"))
            cleanup = bool(raw.get("cleanup_uncertain"))
        else:
            content = str(getattr(raw, "content", raw) or "")
            exit_code = getattr(raw, "exit_code", None)
            status = str(getattr(raw, "status", "") or "")
            duration_ms = int(getattr(raw, "duration_ms", 0) or 0)
            truncated = bool(getattr(raw, "output_truncated", False) or getattr(raw, "truncated_by", None))
            cleanup = bool(getattr(raw, "cleanup_uncertain", False))
        if not duration_ms:
            duration_ms = round((time.monotonic() - started) * 1000)
        if status in {"timed_out", "timeout"}:
            task_status, timed_out = TaskStatus.FAILED, True
        elif status in {"cancelled", "canceled"}:
            task_status, timed_out = TaskStatus.CANCELLED, False
        else:
            try:
                numeric_code = int(exit_code) if exit_code is not None else None
            except (TypeError, ValueError):
                numeric_code = None
            task_status = TaskStatus.UNVERIFIED if numeric_code is None else (
                TaskStatus.VERIFIED if numeric_code == 0 else TaskStatus.FAILED
            )
            timed_out = False
            exit_code = numeric_code
        return VerificationResult(
            task_status,
            command=command,
            source=source,
            exit_code=exit_code,
            duration_ms=duration_ms,
            output_tail=content,
            output_truncated=truncated,
            timed_out=timed_out,
            cancelled=task_status is TaskStatus.CANCELLED,
            cleanup_uncertain=cleanup,
        )
