"""Provider-neutral tool lifecycle status contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .messages import CleanupStatus, ToolExecutionStatus

__all__ = ["ToolLifecycleStatus", "ToolStatusSnapshot"]


class ToolLifecycleStatus:
    """Stable lifecycle values shared by execution events and consumers."""

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    CLEANUP_UNCERTAIN = "cleanup_uncertain"

    ALL = (
        QUEUED,
        RUNNING,
        AWAITING_CONFIRMATION,
        COMPLETED,
        FAILED,
        REJECTED,
        TIMED_OUT,
        CANCELLED,
        CLEANUP_UNCERTAIN,
    )
    TERMINAL = (
        COMPLETED,
        FAILED,
        REJECTED,
        TIMED_OUT,
        CANCELLED,
        CLEANUP_UNCERTAIN,
    )

    @classmethod
    def normalize(cls, value: Any) -> str:
        """Normalize legacy result values to the lifecycle vocabulary."""
        normalized = str(value or cls.QUEUED)
        if normalized == ToolExecutionStatus.OK:
            normalized = cls.COMPLETED
        if normalized not in cls.ALL:
            raise ValueError(f"unsupported tool lifecycle status: {normalized}")
        return normalized


@dataclass(frozen=True)
class ToolStatusSnapshot:
    """Immutable, serializable facts for one tool call's current state."""

    tool_call_id: str
    operation_id: str | None = None
    tool_name: str = ""
    status: str = ToolLifecycleStatus.QUEUED
    cleanup_status: str = CleanupStatus.NOT_REQUIRED
    elapsed_ms: int | None = None
    error_code: str | None = None
    queue_position: int | None = None

    def __post_init__(self) -> None:
        if not self.tool_call_id:
            raise ValueError("tool_call_id must be non-empty")
        object.__setattr__(self, "status", ToolLifecycleStatus.normalize(self.status))
        if self.cleanup_status not in CleanupStatus.ALL:
            raise ValueError(f"unsupported cleanup status: {self.cleanup_status}")
        for name in ("elapsed_ms", "queue_position"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")

    @property
    def is_terminal(self) -> bool:
        """Whether this call has reached a final execution state."""
        return self.status in ToolLifecycleStatus.TERMINAL

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-safe representation."""
        return {
            "tool_call_id": self.tool_call_id,
            "operation_id": self.operation_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "cleanup_status": self.cleanup_status,
            "elapsed_ms": self.elapsed_ms,
            "error_code": self.error_code,
            "queue_position": self.queue_position,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ToolStatusSnapshot":
        """Read a current or legacy snapshot without requiring every field."""
        data = dict(value) if isinstance(value, dict) else {}
        return cls(
            tool_call_id=str(data.get("tool_call_id") or "unknown"),
            operation_id=data.get("operation_id"),
            tool_name=str(data.get("tool_name") or ""),
            status=data.get("status") or ToolLifecycleStatus.QUEUED,
            cleanup_status=str(data.get("cleanup_status") or CleanupStatus.NOT_REQUIRED),
            elapsed_ms=data.get("elapsed_ms"),
            error_code=data.get("error_code"),
            queue_position=data.get("queue_position"),
        )
