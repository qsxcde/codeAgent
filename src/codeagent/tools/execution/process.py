"""跨平台同步/异步进程执行器。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from codeagent.tools.execution.posix import PosixProcessBackend
from codeagent.tools.execution.windows import WindowsProcessBackend

__all__ = ["ProcessRequest", "ProcessResult", "ProcessRunner"]


class _ProcessBackend(Protocol):
    def spawn_kwargs(self, cwd: str, env: dict[str, str]) -> dict[str, Any]: ...

    def async_spawn_kwargs(self, cwd: str, env: dict[str, str]) -> dict[str, Any]: ...

    def kill_tree(self, pid: int) -> bool: ...


@dataclass(frozen=True)
class ProcessRequest:
    """平台无关的进程执行请求。"""

    executable: str
    command: str
    cwd: str
    env: dict[str, str]
    timeout: int


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cleanup_confirmed: bool = True


def _default_backend() -> _ProcessBackend:
    return WindowsProcessBackend() if os.name == "nt" else PosixProcessBackend()


class ProcessRunner:
    """以统一结果契约执行一个非交互式 Shell 进程。"""

    def __init__(self, backend: _ProcessBackend | None = None) -> None:
        self._backend = backend or _default_backend()

    @staticmethod
    def _read_output(path: str) -> str:
        return Path(path).read_bytes().decode("utf-8", errors="replace")

    @staticmethod
    def _create_output_files() -> tuple[int, str, int, str]:
        fd_out, out_name = tempfile.mkstemp(prefix="pi-bash-")
        fd_err, err_name = tempfile.mkstemp(prefix="pi-bash-")
        os.close(fd_out)
        os.close(fd_err)
        return fd_out, out_name, fd_err, err_name

    @staticmethod
    def _cleanup(paths: tuple[str, str]) -> None:
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def run(
        self,
        request: ProcessRequest,
    ) -> ProcessResult:
        _, out_name, _, err_name = self._create_output_files()
        paths = (out_name, err_name)
        try:
            with open(out_name, "wb") as out_file, open(err_name, "wb") as err_file:
                proc = subprocess.Popen(
                    [request.executable, "-lc", request.command],
                    stdout=out_file,
                    stderr=err_file,
                    **self._backend.spawn_kwargs(request.cwd, request.env),
                )
            timed_out = False
            cleanup_confirmed = True
            try:
                proc.wait(timeout=request.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                cleanup_confirmed = self._backend.kill_tree(proc.pid)
                proc.wait()
            return ProcessResult(
                proc.returncode,
                self._read_output(out_name),
                self._read_output(err_name),
                timed_out,
                cleanup_confirmed,
            )
        finally:
            self._cleanup(paths)

    async def arun(
        self,
        request: ProcessRequest,
    ) -> ProcessResult:
        _, out_name, _, err_name = self._create_output_files()
        paths = (out_name, err_name)
        proc: asyncio.subprocess.Process | None = None
        cleanup_confirmed = True
        try:
            with open(out_name, "wb") as out_file, open(err_name, "wb") as err_file:
                proc = await asyncio.create_subprocess_exec(
                    request.executable,
                    "-lc",
                    request.command,
                    stdout=out_file,
                    stderr=err_file,
                    **self._backend.async_spawn_kwargs(request.cwd, request.env),
                )
            timed_out = False
            try:
                await asyncio.wait_for(proc.wait(), timeout=request.timeout)
            except asyncio.TimeoutError:
                timed_out = True
                cleanup_confirmed = self._backend.kill_tree(proc.pid)
                await proc.wait()
            except asyncio.CancelledError:
                cleanup_confirmed = self._backend.kill_tree(proc.pid)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except Exception:
                    cleanup_confirmed = False
                raise
            return ProcessResult(
                proc.returncode or 0,
                self._read_output(out_name),
                self._read_output(err_name),
                timed_out,
                cleanup_confirmed,
            )
        finally:
            self._cleanup(paths)
