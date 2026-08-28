"""工作区快照和验证命令发现。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

from ..modes import is_mutating_command

from .models import VerificationCommand, WorkspaceDiff, WorkspaceSnapshot


class WorkspaceInspector:
    """通过内容快照判定实际变更，Git 状态仅作为辅助信息。"""

    DEFAULT_EXCLUDES = frozenset(
        {".git", ".codeagent", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache", ".venv", "venv", "node_modules"}
    )

    def __init__(self, cwd: str | Path, *, excludes: set[str] | None = None) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.excludes = self.DEFAULT_EXCLUDES | set(excludes or ())

    def capture(self) -> WorkspaceSnapshot:
        files: dict[str, str] = {}
        if self.cwd.exists():
            for path in self.cwd.rglob("*"):
                if path.is_file() and not self._excluded(path):
                    try:
                        files[path.relative_to(self.cwd).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
                    except OSError:
                        continue
        return WorkspaceSnapshot(files, self._git_status())

    def compare(self, before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> WorkspaceDiff:
        before_keys, after_keys = set(before.files), set(after.files)
        added, deleted = after_keys - before_keys, before_keys - after_keys
        modified = {path for path in before_keys & after_keys if before.files[path] != after.files[path]}
        return WorkspaceDiff(
            changed_files=tuple(sorted(added | modified | deleted)),
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
        return tuple(line for line in result.stdout.splitlines() if line.strip()) if result.returncode == 0 else ()


class VerificationCommandResolver:
    """按显式命令、配置和项目特征选择验证命令。"""

    def __init__(self, cwd: str | Path) -> None:
        self.cwd = Path(cwd).expanduser().resolve()

    def resolve(self, explicit: str | None = None, *, configured: str | None = None) -> VerificationCommand | None:
        if explicit and explicit.strip():
            return VerificationCommand(explicit.strip(), "explicit")
        configured = configured or self._from_project_config()
        return VerificationCommand(configured.strip(), "config") if configured and configured.strip() else self._detect()

    def _from_project_config(self) -> str | None:
        pyproject = self.cwd / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                codeagent = data.get("tool", {}).get("codeagent", {})
                if isinstance(codeagent, dict) and isinstance(codeagent.get("verify") or codeagent.get("test_command"), str):
                    return codeagent.get("verify") or codeagent.get("test_command")
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
        if (self.cwd / "pyproject.toml").is_file() and ((self.cwd / "tests").is_dir() or (self.cwd / "test").is_dir()):
            command = "uv run pytest -q" if shutil.which("uv") else "python -m pytest -q"
            return VerificationCommand(command, "detect:python")
        package = self.cwd / "package.json"
        if package.is_file():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
                if isinstance(scripts, dict) and scripts.get("test"):
                    return VerificationCommand("npm test", "detect:node")
            except (OSError, ValueError):
                pass
        candidates = {
            "Cargo.toml": ("cargo test", "detect:rust"),
            "go.mod": ("go test ./...", "detect:go"),
            "pom.xml": ("mvn test", "detect:java"),
        }
        for marker, value in candidates.items():
            if (self.cwd / marker).is_file():
                return VerificationCommand(*value)
        if list(self.cwd.glob("*.sln")) or list(self.cwd.glob("*.csproj")):
            return VerificationCommand("dotnet test", "detect:dotnet")
        makefile = self.cwd / "Makefile"
        if makefile.is_file():
            try:
                if any(line.startswith("test:") for line in makefile.read_text(encoding="utf-8", errors="ignore").splitlines()):
                    return VerificationCommand("make test", "detect:make")
            except OSError:
                pass
        return None
