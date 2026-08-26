"""Bash 原子工具适配层。

进程生命周期、平台差异、环境隔离和危险命令规则分别由
``tools.execution`` 与 ``tools.security`` 提供；本模块只保留 Bash 工具
的参数契约、退出码语义和结果格式化。
"""

from __future__ import annotations

import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.execution import ProcessRequest, ProcessRunner, bash_env, resolve_bash
from codeagent.tools.security.bash_rules import (
    DANGEROUS_PATTERNS,
    _SEGMENT_SEPARATORS,
    _dangerous_hit,
    _dangerous_intent,
)
from codeagent.tools.shared import DEFAULT_MAX_LINES, truncate_tail

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
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.strip().split()
    if not tokens:
        return ""
    last_segment: list[str] = []
    for token in tokens:
        if token in _SEGMENT_SEPARATORS:
            last_segment = []
        else:
            last_segment.append(token)
    return last_segment[0] if last_segment else tokens[0]


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

    def __init__(
        self,
        *,
        cwd: str | None = None,
        ops=None,
        runner: ProcessRunner | None = None,
    ) -> None:
        super().__init__(cwd=cwd, ops=ops)
        self._runner = runner or ProcessRunner()

    @staticmethod
    def _timeout(args: BashArgs) -> int:
        requested = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT_S
        return max(1, min(requested, MAX_TIMEOUT_S))

    def _validate_command(self, args: BashArgs) -> tuple[str, int]:
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
                )
            )
        except OSError as exc:
            raise ValueError(f"命令执行失败: {exc}") from exc
        return self._format_result(
            command,
            timeout,
            result.returncode,
            result.stdout,
            result.stderr,
            result.timed_out,
            time.monotonic() - started,
        )

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
                )
            )
        except OSError as exc:
            raise ValueError(f"命令执行失败: {exc}") from exc
        content = self._format_result(
            command,
            timeout,
            result.returncode,
            result.stdout,
            result.stderr,
            result.timed_out,
            time.monotonic() - started,
        )
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
        )

    def _format_result(
        self,
        command: str,
        timeout: int,
        returncode: int,
        stdout: str,
        stderr: str,
        timed_out: bool,
        elapsed: float,
    ) -> str:
        if timed_out:
            return f"[命令超时(>{timeout}s),已终止]\n命令: {command}\n{stdout}{stderr}"

        stdout_t, out_truncated = truncate_tail(
            stdout, max_lines=DEFAULT_MAX_LINES, max_bytes=MAX_OUTPUT_CHARS
        )
        stderr_t, err_truncated = truncate_tail(
            stderr, max_lines=DEFAULT_MAX_LINES, max_bytes=MAX_OUTPUT_CHARS
        )
        if out_truncated.truncated:
            stdout_t += TRUNCATION_MARKER
        if err_truncated.truncated:
            stderr_t += TRUNCATION_MARKER

        if not _semantically_ok(returncode, command):
            header = f"退出码: {returncode}(命令失败,耗时 {elapsed:.1f}s)"
        else:
            header = f"退出码: {returncode}(耗时 {elapsed:.1f}s)"
        if stderr_t.strip():
            return f"{header}\nstdout:\n{stdout_t}\nstderr:\n{stderr_t}"
        return f"{header}\nstdout:\n{stdout_t}"

    def _bash_env(self) -> dict[str, str]:
        return bash_env()
