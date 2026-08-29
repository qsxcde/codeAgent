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
from codeagent.tools.shared import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES

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
    max_output_bytes: int = DEFAULT_MAX_BYTES
    max_output_lines: int = DEFAULT_MAX_LINES
    output_direction: str = "head"


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cleanup_confirmed: bool = True
    stdout_total_bytes: int = 0
    stdout_total_lines: int = 0
    stdout_shown_bytes: int = 0
    stdout_shown_lines: int = 0
    stdout_truncated: bool = False
    stderr_total_bytes: int = 0
    stderr_total_lines: int = 0
    stderr_shown_bytes: int = 0
    stderr_shown_lines: int = 0
    stderr_truncated: bool = False


def _default_backend() -> _ProcessBackend:
    return WindowsProcessBackend() if os.name == "nt" else PosixProcessBackend()


class ProcessRunner:
    """以统一结果契约执行一个非交互式 Shell 进程。"""

    def __init__(self, backend: _ProcessBackend | None = None) -> None:
        self._backend = backend or _default_backend()

    @staticmethod
    def _read_output(path: str, request: ProcessRequest) -> tuple[str, tuple[int, int, int, int, bool]]:
        return _capture_file(
            path,
            max_bytes=request.max_output_bytes,
            max_lines=request.max_output_lines,
            direction=request.output_direction,
        )

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
            stdout, stdout_stats = self._read_output(out_name, request)
            stderr, stderr_stats = self._read_output(err_name, request)
            return _process_result(
                proc.returncode,
                stdout,
                stderr,
                timed_out,
                cleanup_confirmed,
                stdout_stats,
                stderr_stats,
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
            stdout, stdout_stats = self._read_output(out_name, request)
            stderr, stderr_stats = self._read_output(err_name, request)
            return _process_result(
                proc.returncode or 0,
                stdout,
                stderr,
                timed_out,
                cleanup_confirmed,
                stdout_stats,
                stderr_stats,
            )
        finally:
            self._cleanup(paths)


def _capture_file(
    path: str,
    *,
    max_bytes: int,
    max_lines: int,
    direction: str,
) -> tuple[str, tuple[int, int, int, int, bool]]:
    """Read a bounded preview while counting the complete file by chunks."""
    if max_bytes < 1 or max_lines < 1:
        raise ValueError("output limits must be positive")
    total_bytes = 0
    newline_count = 0
    last_byte = b""
    with open(path, "rb") as stream:
        while chunk := stream.read(64 * 1024):
            total_bytes += len(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
    total_lines = newline_count + int(total_bytes > 0 and last_byte != b"\n")
    with open(path, "rb") as stream:
        if direction == "tail" and total_bytes > max_bytes:
            stream.seek(-max_bytes, os.SEEK_END)
        raw = stream.read(max_bytes)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated_by_lines = len(lines) > max_lines
    if truncated_by_lines:
        lines = lines[-max_lines:] if direction == "tail" else lines[:max_lines]
        text = "\n".join(lines)
    shown_bytes = len(text.encode("utf-8"))
    shown_lines = len(text.splitlines())
    truncated = total_bytes > max_bytes or total_lines > max_lines
    return text, (total_bytes, total_lines, shown_bytes, shown_lines, truncated)


def _process_result(
    returncode: int,
    stdout: str,
    stderr: str,
    timed_out: bool,
    cleanup_confirmed: bool,
    stdout_stats: tuple[int, int, int, int, bool],
    stderr_stats: tuple[int, int, int, int, bool],
) -> ProcessResult:
    return ProcessResult(
        returncode,
        stdout,
        stderr,
        timed_out,
        cleanup_confirmed,
        *stdout_stats,
        *stderr_stats,
    )
