"""任务监督事件和结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .modes import TaskMode
from .verification.models import TaskStatus, VerificationResult


class TaskPhase(StrEnum):
    PLANNING = "planning"
    EDITING = "editing"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    UNVERIFIED = "unverified"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True)
class TaskEvent:
    phase: TaskPhase
    message: str = ""
    command: str = ""
    attempt: int = 0
    max_attempts: int = 0
    elapsed_ms: int = 0
    result: VerificationResult | None = None


@dataclass(frozen=True)
class TaskResult:
    status: TaskStatus
    mode: TaskMode
    changed_files: tuple[str, ...] = ()
    verification: VerificationResult | None = None
    repair_attempts: int = 0
    message: str = ""
