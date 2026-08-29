"""Bash 原子工具适配层。

进程生命周期、平台差异、环境隔离和危险命令规则分别由
``tools.execution`` 与 ``tools.security`` 提供；本模块只保留 Bash 工具
的参数契约、退出码语义和结果格式化。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.execution import ProcessRequest, ProcessRunner, bash_env, resolve_bash
from codeagent.tools.security.bash_rules import (
    DANGEROUS_PATTERNS,
    _dangerous_hit,
    _dangerous_intent,
)
from codeagent.tools.security.shell_parse import last_segment_first_token
from codeagent.tools.shared import GovernedText, ToolResourceLimits, redact_metadata_text

__all__ = [
    "BashTool",
    "BashInvocationResult",
    "DEFAULT_TIMEOUT_S",
    "MAX_TIMEOUT_S",
    "MAX_OUTPUT_CHARS",
    "DANGEROUS_PATTERNS",
]


@dataclass(frozen=True)
class BashInvocationResult:
    """Async bash result understood by the core runtime via duck typing."""

    content: str
    status: str = "completed"
    cleanup_confirmed: bool | None = True
    exit_code: int | None = None
    duration_ms: int = 0
    output_truncated: bool = False
    success: bool | None = None
    output_metadata: dict[str, Any] | None = None

    @property
    def cleanup_uncertain(self) -> bool:
        return self.cleanup_confirmed is False


DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600
MAX_OUTPUT_CHARS = 30_000
SEMANTIC_OK_PREFIXES = ("grep",)
TRUNCATION_MARKER = "\n...[输出已截断(保留末尾)]..."


class BashArgs(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
    timeout: int | None = Field(None, description="超时秒数,缺省 120,上限 600")


def _last_segment_first_token(command: str) -> str:
    """取最后一个逻辑段的首 token，用于退出码语义判断。"""
    return last_segment_first_token(command)


def _semantically_ok(exit_code: int, command: str) -> bool:
    """grep 无匹配等已知语义性非零退出码不视为失败。"""
    if exit_code == 0:
        return True
    return _last_segment_first_token(command) in SEMANTIC_OK_PREFIXES


class BashTool(AtomicTool):
    name = "bash"
    description = (
        "执行 shell 命令并返回输出与退出码;默认超时 120s;"
        "grep 无匹配(退出码 1)不视为错误;危险命令会被拒绝。"
    )
    Args = BashArgs

    @property
    def supports_cancellation(self) -> bool:
        """POSIX process groups are verifiable; Windows tree kill is best effort."""
        return os.name != "nt"

    def __init__(
        self,
        *,
        cwd: str | None = None,
        ops=None,
        runner: ProcessRunner | None = None,
        resource_limits: ToolResourceLimits | None = None,
    ) -> None:
        super().__init__(cwd=cwd, ops=ops, resource_limits=resource_limits)
        self._runner = runner or ProcessRunner()

    def _timeout(self, args: BashArgs) -> float:
        requested = (
            args.timeout
            if args.timeout is not None
            else self.resource_limits.timeout or DEFAULT_TIMEOUT_S
        )
        maximum = min(MAX_TIMEOUT_S, self.resource_limits.max_timeout)
        return max(0.001, min(float(requested), maximum))

    def _validate_command(self, args: BashArgs) -> tuple[str, float]:
        command = args.command.strip()
        if not command:
            raise ValueError("命令为空")
        hit = _dangerous_hit(command) or _dangerous_intent(command, self._cwd)
        if hit is not None:
            raise ValueError(f"命令命中危险模式,已拒绝执行: {hit}\n命令: {command}")
        return command, self._timeout(args)

    def _invoke(self, args: BashArgs) -> str:
        command, timeout = self._validate_command(args)
        started = time.monotonic()
        try:
            result = self._runner.run(
                ProcessRequest(
                    resolve_bash(),
                    command,
                    str(self._cwd or Path.cwd()),
                    self._bash_env(),
                    timeout,
                    max_output_bytes=self.resource_limits.max_output_bytes,
                    max_output_lines=self.output_max_lines,
                    output_direction="tail",
                    max_memory_bytes=self.resource_limits.max_memory_bytes,
                    cleanup_timeout=self.resource_limits.cleanup_timeout,
                )
            )
        except OSError as exc:
            raise ValueError(f"命令执行失败: {exc}") from exc
        return self._format_result(command, timeout, result, time.monotonic() - started)

    async def ainvoke(self, args: BashArgs) -> BashInvocationResult:
        """可取消的异步路径；取消时由 ProcessRunner 负责清理进程树。"""
        command, timeout = self._validate_command(args)
        started = time.monotonic()
        try:
            result = await self._runner.arun(
                ProcessRequest(
                    resolve_bash(),
                    command,
                    str(self._cwd or Path.cwd()),
                    self._bash_env(),
                    timeout,
                    max_output_bytes=self.resource_limits.max_output_bytes,
                    max_output_lines=self.output_max_lines,
                    output_direction="tail",
                    max_memory_bytes=self.resource_limits.max_memory_bytes,
                    cleanup_timeout=self.resource_limits.cleanup_timeout,
                )
            )
        except OSError as exc:
            raise ValueError(f"命令执行失败: {exc}") from exc
        content = self._format_result(command, timeout, result, time.monotonic() - started)
        duration = round((time.monotonic() - started) * 1000)
        if result.timed_out:
            status = "timed_out" if result.cleanup_confirmed else "cleanup_uncertain"
            success = False
        else:
            success = _semantically_ok(result.returncode, command)
            status = "completed" if success else "failed"
        return BashInvocationResult(
            content,
            status,
            result.cleanup_confirmed,
            exit_code=result.returncode,
            duration_ms=duration,
            output_truncated=TRUNCATION_MARKER in content,
            success=success,
            output_metadata=content.output_metadata,
        )

    def _format_result(
        self,
        command: str,
        timeout: float,
        result,
        elapsed: float,
    ) -> GovernedText:
        stdout = result.stdout
        stderr = result.stderr
        stdout_stats = _stream_stats(result, "stdout", stdout)
        stderr_stats = _stream_stats(result, "stderr", stderr)
        truncated = bool(stdout_stats[4] or stderr_stats[4])
        reason = _truncation_reason(stdout_stats, stderr_stats)
        output_metadata = {
            "completeness": "incomplete" if result.timed_out else ("truncated" if truncated else "complete"),
            "total_bytes": stdout_stats[0] + stderr_stats[0],
            "total_lines": stdout_stats[1] + stderr_stats[1],
            "shown_bytes": stdout_stats[2] + stderr_stats[2],
            "shown_lines": stdout_stats[3] + stderr_stats[3],
            "truncated_by": "timeout" if result.timed_out else reason,
            "exit_code": result.returncode,
            "duration_ms": round(elapsed * 1000),
            "stderr_summary": redact_metadata_text(stderr[:1000]) if stderr else None,
            "semantic_success": None if result.timed_out else _semantically_ok(result.returncode, command),
            "source": "tool",
        }
        stdout = stdout + TRUNCATION_MARKER if stdout_stats[4] else stdout
        stderr = stderr + TRUNCATION_MARKER if stderr_stats[4] else stderr
        if result.timed_out:
            return GovernedText(
                f"[命令超时(>{timeout}s),已终止]\n命令: {command}\n{stdout}{stderr}",
                output_metadata,
            )

        if not _semantically_ok(result.returncode, command):
            header = f"退出码: {result.returncode}(命令失败,耗时 {elapsed:.1f}s)"
        else:
            header = f"退出码: {result.returncode}(耗时 {elapsed:.1f}s)"
        if stderr.strip():
            content = f"{header}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        else:
            content = f"{header}\nstdout:\n{stdout}"
        return GovernedText(content, output_metadata)

    def _bash_env(self) -> dict[str, str]:
        return bash_env()


def _stream_stats(
    result: Any, name: str, content: str
) -> tuple[int, int, int, int, bool, str | None]:
    """Read ProcessResult statistics with a compatibility fallback."""
    value = len(content.encode("utf-8"))
    lines = len(content.splitlines())
    prefix = f"{name}_"
    total_bytes = int(getattr(result, prefix + "total_bytes", 0) or value)
    total_lines = int(getattr(result, prefix + "total_lines", 0) or lines)
    shown_bytes = int(getattr(result, prefix + "shown_bytes", 0) or value)
    shown_lines = int(getattr(result, prefix + "shown_lines", 0) or lines)
    truncated = bool(getattr(result, prefix + "truncated", False))
    truncated_by = getattr(result, prefix + "truncated_by", None)
    return total_bytes, total_lines, shown_bytes, shown_lines, truncated, truncated_by


def _truncation_reason(*stats: tuple[int, int, int, int, bool, str | None]) -> str | None:
    for item in stats:
        if item[5] is not None:
            return item[5]
    if any(item[4] and item[0] > item[2] for item in stats):
        return "tool_bytes"
    if any(item[4] and item[1] > item[3] for item in stats):
        return "tool_lines"
    return None
