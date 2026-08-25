"""工作区变更检测和验证命令执行。

这些组件是无 UI 的应用层服务，既可被 CLI/TUI 复用，也可通过注入执行器
离线测试。验证结论只依赖结构化退出码，不解析 bash 的展示文本。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Awaitable, Callable

from codeagent.app.task_modes import is_mutating_command

__all__ = [
    "TaskStatus",
    "WorkspaceSnapshot",
    "WorkspaceDiff",
    "WorkspaceInspector",
    "VerificationCommand",
    "VerificationCommandResolver",
    "VerificationResult",
    "VerificationRunner",
]


class TaskStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True)
class WorkspaceSnapshot:
    files: dict[str, str]
    git_status: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkspaceDiff:
    changed_files: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_files)

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.added:
            parts.append(f"+{len(self.added)}")
        if self.modified:
            parts.append(f"~{len(self.modified)}")
        if self.deleted:
            parts.append(f"-{len(self.deleted)}")
        return " ".join(parts) or "无变更"


class WorkspaceInspector:
    """通过内容快照判定实际变更，Git 状态仅作为可观察辅助信息。"""

    DEFAULT_EXCLUDES = frozenset(
        {
            ".git",
            ".codeagent",
            ".pytest_cache",
            "__pycache__",
            ".mypy_cache",
            ".ruff_cache",
            ".venv",
            "venv",
            "node_modules",
        }
    )

    def __init__(self, cwd: str | Path, *, excludes: set[str] | None = None) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.excludes = self.DEFAULT_EXCLUDES | set(excludes or ())

    def capture(self) -> WorkspaceSnapshot:
        files: dict[str, str] = {}
        if self.cwd.exists():
            for path in self.cwd.rglob("*"):
                if not path.is_file() or self._excluded(path):
                    continue
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    continue
                files[path.relative_to(self.cwd).as_posix()] = digest
        return WorkspaceSnapshot(files, self._git_status())

    def compare(
        self, before: WorkspaceSnapshot, after: WorkspaceSnapshot
    ) -> WorkspaceDiff:
        before_keys = set(before.files)
        after_keys = set(after.files)
        added = after_keys - before_keys
        deleted = before_keys - after_keys
        modified = {
            path
            for path in before_keys & after_keys
            if before.files[path] != after.files[path]
        }
        changed = tuple(sorted(added | modified | deleted))
        return WorkspaceDiff(
            changed_files=changed,
            added=tuple(sorted(added)),
            modified=tuple(sorted(modified)),
            deleted=tuple(sorted(deleted)),
        )

    def _excluded(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.cwd)
        except ValueError:
            return True
        return any(part in self.excludes for part in relative.parts)

    def _git_status(self) -> tuple[str, ...]:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=self.cwd,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ()
        if result.returncode != 0:
            return ()
        return tuple(line for line in result.stdout.splitlines() if line.strip())


@dataclass(frozen=True)
class VerificationCommand:
    command: str
    source: str


class VerificationCommandResolver:
    """按显式命令、配置、项目特征选择验证命令。"""

    def __init__(self, cwd: str | Path) -> None:
        self.cwd = Path(cwd).expanduser().resolve()

    def resolve(
        self,
        explicit: str | None = None,
        *,
        configured: str | None = None,
    ) -> VerificationCommand | None:
        if explicit and explicit.strip():
            return VerificationCommand(explicit.strip(), "explicit")
        configured = configured or self._from_project_config()
        if configured and configured.strip():
            return VerificationCommand(configured.strip(), "config")
        return self._detect()

    def _from_project_config(self) -> str | None:
        pyproject = self.cwd / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                tool = data.get("tool", {})
                codeagent = tool.get("codeagent", {}) if isinstance(tool, dict) else {}
                if isinstance(codeagent, dict):
                    value = codeagent.get("verify") or codeagent.get("test_command")
                    if isinstance(value, str):
                        return value
            except (OSError, tomllib.TOMLDecodeError):
                pass
        package = self.cwd / "package.json"
        if package.is_file():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
                if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
                    return "npm test"
            except (OSError, ValueError):
                pass
        return None

    def _detect(self) -> VerificationCommand | None:
        if (self.cwd / "pyproject.toml").is_file() and (
            (self.cwd / "tests").is_dir() or (self.cwd / "test").is_dir()
        ):
            executable = "uv" if shutil.which("uv") else "python"
            command = "uv run pytest -q" if executable == "uv" else "python -m pytest -q"
            return VerificationCommand(command, "detect:python")
        package = self.cwd / "package.json"
        if package.is_file():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
                if isinstance(scripts, dict) and scripts.get("test"):
                    return VerificationCommand("npm test", "detect:node")
            except (OSError, ValueError):
                pass
        if (self.cwd / "Cargo.toml").is_file():
            return VerificationCommand("cargo test", "detect:rust")
        if (self.cwd / "go.mod").is_file():
            return VerificationCommand("go test ./...", "detect:go")
        if list(self.cwd.glob("*.sln")) or list(self.cwd.glob("*.csproj")):
            return VerificationCommand("dotnet test", "detect:dotnet")
        if (self.cwd / "pom.xml").is_file():
            return VerificationCommand("mvn test", "detect:java")
        makefile = self.cwd / "Makefile"
        if makefile.is_file():
            try:
                text = makefile.read_text(encoding="utf-8", errors="ignore")
                if any(line.startswith("test:") for line in text.splitlines()):
                    return VerificationCommand("make test", "detect:make")
            except OSError:
                pass
        return None


@dataclass(frozen=True)
class VerificationResult:
    status: TaskStatus
    command: str = ""
    source: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    output_tail: str = ""
    output_truncated: bool = False
    timed_out: bool = False
    cancelled: bool = False
    cleanup_uncertain: bool = False


ExecuteFn = Callable[[str, float], Awaitable[Any] | Any]


class VerificationRunner:
    """运行一条验证命令并标准化结果。"""

    def __init__(
        self,
        cwd: str | Path,
        *,
        execute: ExecuteFn | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
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
            elapsed = round((time.monotonic() - started) * 1000)
            return VerificationResult(
                TaskStatus.CANCELLED,
                command=command,
                source=source,
                duration_ms=elapsed,
                cancelled=True,
            )
        except asyncio.TimeoutError:
            elapsed = round((time.monotonic() - started) * 1000)
            return VerificationResult(
                TaskStatus.FAILED,
                command=command,
                source=source,
                duration_ms=elapsed,
                timed_out=True,
            )

        result = self._normalize(raw, command, source, started)
        return result

    async def _execute(self, command: str, timeout: float) -> Any:
        if self.execute is not None:
            value = self.execute(command, timeout)
            return await value if inspect.isawaitable(value) else value
        if os.name == "nt":
            argv = ["cmd.exe", "/d", "/s", "/c", command]
        else:
            argv = ["/bin/sh", "-lc", command]
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.cwd),
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
        max_chars = 12_000
        truncated = len(text) > max_chars
        return {
            "status": "completed" if process.returncode == 0 else "failed",
            "exit_code": process.returncode,
            "content": text[-max_chars:] if truncated else text,
            "output_truncated": truncated,
        }

    @staticmethod
    def _normalize(
        raw: Any, command: str, source: str, started: float
    ) -> VerificationResult:
        if isinstance(raw, dict):
            values = raw
            content = str(values.get("content") or values.get("output_tail") or "")
            exit_code = values.get("exit_code")
            status = str(values.get("status") or "")
            duration_ms = int(values.get("duration_ms") or 0)
            truncated = bool(values.get("output_truncated") or values.get("truncated_by"))
            cleanup = bool(values.get("cleanup_uncertain"))
        else:
            content = str(getattr(raw, "content", raw) or "")
            exit_code = getattr(raw, "exit_code", None)
            status = str(getattr(raw, "status", "") or "")
            duration_ms = int(getattr(raw, "duration_ms", 0) or 0)
            truncated = bool(
                getattr(raw, "output_truncated", False)
                or getattr(raw, "truncated_by", None)
            )
            cleanup = bool(getattr(raw, "cleanup_uncertain", False))
        if not duration_ms:
            duration_ms = round((time.monotonic() - started) * 1000)
        if status in {"timed_out", "timeout"}:
            task_status = TaskStatus.FAILED
            timed_out = True
        elif status in {"cancelled", "canceled"}:
            task_status = TaskStatus.CANCELLED
            timed_out = False
        else:
            try:
                numeric_code = int(exit_code) if exit_code is not None else None
            except (TypeError, ValueError):
                numeric_code = None
            # Unknown exit code is deliberately unverified rather than guessed.
            if numeric_code is None:
                task_status = TaskStatus.UNVERIFIED
            else:
                task_status = TaskStatus.VERIFIED if numeric_code == 0 else TaskStatus.FAILED
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
