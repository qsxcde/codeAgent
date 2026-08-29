"""统一的工具执行资源限制。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any

from .truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES

DEFAULT_TOOL_CONCURRENCY = 4
DEFAULT_TOOL_MAX_TIMEOUT = 600.0
DEFAULT_TOOL_MEMORY_BYTES = 1_048_576
DEFAULT_TOOL_CLEANUP_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class ToolResourceLimits:
    """边界工具共享的并发、超时、输出和清理限制。

    ``max_memory_bytes`` 限制的是从临时输出文件物化到内存的预览大小；
    子进程的完整输出仍保留在临时文件中，以便继续计算总量和截断状态。
    """

    max_concurrency: int = DEFAULT_TOOL_CONCURRENCY
    timeout: float | None = None
    max_timeout: float = DEFAULT_TOOL_MAX_TIMEOUT
    max_output_bytes: int = DEFAULT_MAX_BYTES
    max_output_lines: int = DEFAULT_MAX_LINES
    max_memory_bytes: int = DEFAULT_TOOL_MEMORY_BYTES
    cleanup_timeout: float = DEFAULT_TOOL_CLEANUP_TIMEOUT

    def __post_init__(self) -> None:
        _positive_int(self.max_concurrency, "max_concurrency")
        _positive_int(self.max_output_bytes, "max_output_bytes")
        _positive_int(self.max_output_lines, "max_output_lines")
        _positive_int(self.max_memory_bytes, "max_memory_bytes")
        max_timeout = _positive_number(self.max_timeout, "max_timeout")
        if self.timeout is not None:
            timeout = _positive_number(self.timeout, "timeout")
            if timeout > max_timeout:
                raise ValueError("timeout must not exceed max_timeout")
        _positive_number(self.cleanup_timeout, "cleanup_timeout")

    @property
    def effective_output_bytes(self) -> int:
        """返回同时满足输出上限和预览内存上限的字节上限。"""
        return min(self.max_output_bytes, self.max_memory_bytes)

    @classmethod
    def from_config(cls, cfg: Any = None) -> "ToolResourceLimits":
        """从应用配置读取工具资源字段；缺失字段使用兼容默认值。"""
        if isinstance(cfg, cls):
            return cfg

        def read(name: str, default: Any) -> Any:
            if cfg is None:
                return default
            if isinstance(cfg, Mapping):
                return cfg.get(name, default)
            return getattr(cfg, name, default)

        return cls(
            max_concurrency=read("tool_max_concurrency", DEFAULT_TOOL_CONCURRENCY),
            timeout=read("tool_timeout", None),
            max_timeout=read("tool_max_timeout", DEFAULT_TOOL_MAX_TIMEOUT),
            max_output_bytes=read("tool_max_output_bytes", DEFAULT_MAX_BYTES),
            max_output_lines=read("tool_max_output_lines", DEFAULT_MAX_LINES),
            max_memory_bytes=read("tool_max_memory_bytes", DEFAULT_TOOL_MEMORY_BYTES),
            cleanup_timeout=read(
                "tool_cleanup_timeout", DEFAULT_TOOL_CLEANUP_TIMEOUT
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        """返回可用于状态展示和诊断的稳定字段。"""
        values = asdict(self)
        values["effective_output_bytes"] = self.effective_output_bytes
        return values


def _positive_int(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_number(value: Real, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)
