"""任务验证的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


@dataclass(frozen=True)
class VerificationCommand:
    command: str
    source: str


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
