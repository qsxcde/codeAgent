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
    timeout: float
    max_output_bytes: int = DEFAULT_MAX_BYTES
    max_output_lines: int = DEFAULT_MAX_LINES
    output_direction: str = "head"
    max_memory_bytes: int | None = None
    cleanup_timeout: float = 10.0

    def __post_init__(self) -> None:
        if type(self.timeout) not in (int, float) or self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if type(self.max_output_bytes) is not int or self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be a positive integer")
        if type(self.max_output_lines) is not int or self.max_output_lines <= 0:
            raise ValueError("max_output_lines must be a positive integer")
        if self.max_memory_bytes is not None and (
            type(self.max_memory_bytes) is not int or self.max_memory_bytes <= 0
        ):
            raise ValueError("max_memory_bytes must be a positive integer")
        if (
            type(self.cleanup_timeout) not in (int, float)
            or self.cleanup_timeout <= 0
        ):
            raise ValueError("cleanup_timeout must be positive")


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
    stdout_truncated_by: str | None = None
    stderr_total_bytes: int = 0
    stderr_total_lines: int = 0
    stderr_shown_bytes: int = 0
    stderr_shown_lines: int = 0
    stderr_truncated: bool = False
    stderr_truncated_by: str | None = None


def _default_backend() -> _ProcessBackend:
    return WindowsProcessBackend() if os.name == "nt" else PosixProcessBackend()


class ProcessRunner:
    """以统一结果契约执行一个非交互式 Shell 进程。"""

    def __init__(self, backend: _ProcessBackend | None = None) -> None:
        self._backend = backend or _default_backend()

    @staticmethod
    def _read_output(
        path: str, request: ProcessRequest
    ) -> tuple[str, tuple[int, int, int, int, bool, str | None]]:
        return _capture_file(
            path,
            max_bytes=request.max_output_bytes,
            max_lines=request.max_output_lines,
            direction=request.output_direction,
            max_memory_bytes=request.max_memory_bytes,
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
                try:
                    proc.wait(timeout=request.cleanup_timeout)
                except subprocess.TimeoutExpired:
                    cleanup_confirmed = False
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
                try:
                    await asyncio.wait_for(
                        proc.wait(), timeout=request.cleanup_timeout
                    )
                except (asyncio.TimeoutError, ProcessLookupError):
                    cleanup_confirmed = False
            except asyncio.CancelledError:
                cleanup_confirmed = self._backend.kill_tree(proc.pid)
                try:
                    await asyncio.wait_for(
                        proc.wait(), timeout=request.cleanup_timeout
                    )
                except (asyncio.TimeoutError, ProcessLookupError):
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
    max_memory_bytes: int | None,
) -> tuple[str, tuple[int, int, int, int, bool, str | None]]:
    """Read a bounded preview while counting the complete file by chunks."""
    if max_bytes < 1 or max_lines < 1:
        raise ValueError("output limits must be positive")
    capture_bytes = min(max_bytes, max_memory_bytes) if max_memory_bytes is not None else max_bytes
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
        if direction == "tail" and total_bytes > capture_bytes:
            stream.seek(-capture_bytes, os.SEEK_END)
        raw = stream.read(capture_bytes)
    text = _decode_bounded(raw, capture_bytes)
    lines = text.splitlines()
    truncated_by_lines = len(lines) > max_lines
    if truncated_by_lines:
        lines = lines[-max_lines:] if direction == "tail" else lines[:max_lines]
        text = "\n".join(lines)
    shown_bytes = len(text.encode("utf-8"))
    shown_lines = len(text.splitlines())
    truncated = total_bytes > capture_bytes or total_lines > max_lines
    if max_memory_bytes is not None and total_bytes > max_memory_bytes:
        truncated_by = "tool_memory"
    elif total_bytes > max_bytes:
        truncated_by = "tool_bytes"
    elif total_lines > max_lines:
        truncated_by = "tool_lines"
    else:
        truncated_by = None
    return text, (
        total_bytes,
        total_lines,
        shown_bytes,
        shown_lines,
        truncated,
        truncated_by,
    )


def _decode_bounded(raw: bytes, max_bytes: int) -> str:
    """Decode a preview without allowing replacement characters to exceed its cap."""
    text = raw.decode("utf-8", errors="replace")
    encoded_size = len(text.encode("utf-8"))
    if encoded_size <= max_bytes:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(text[:middle].encode("utf-8")) <= max_bytes:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _process_result(
    returncode: int,
    stdout: str,
    stderr: str,
    timed_out: bool,
    cleanup_confirmed: bool,
    stdout_stats: tuple[int, int, int, int, bool, str | None],
    stderr_stats: tuple[int, int, int, int, bool, str | None],
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
