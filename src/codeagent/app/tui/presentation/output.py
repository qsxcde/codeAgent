"""工具结果的非持久化统计、预览分页和显式导出模型。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeagent.core.contracts.messages import ToolOutputMetadata

__all__ = ["OutputMetadata", "OutputBuffer"]


@dataclass(frozen=True)
class OutputMetadata:
    """工具层输出统计；不会写入会话消息。"""

    total_bytes: int = 0
    total_lines: int = 0
    shown_lines: int = 0
    truncated_by: str | None = None
    artifact_path: str | None = None
    completeness: str | None = None
    shown_bytes: int | None = None
    path: str | None = None
    range_start: int | None = None
    range_end: int | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    stderr_summary: str | None = None
    change_summary: str | None = None
    artifact_ref: str | None = None
    continuation: str | None = None
    semantic_success: bool | None = None
    source: str = "legacy"
    unsupported_blocks: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_value(cls, value: ToolOutputMetadata | dict[str, Any]) -> "OutputMetadata":
        """Convert the core or event representation to a TUI snapshot."""
        if isinstance(value, ToolOutputMetadata):
            data = value.to_dict()
        else:
            data = dict(value)
        return cls(
            total_bytes=data.get("total_bytes") or 0,
            total_lines=data.get("total_lines") or 0,
            shown_lines=data.get("shown_lines") or 0,
            truncated_by=data.get("truncated_by"),
            artifact_path=data.get("artifact_path"),
            completeness=data.get("completeness"),
            shown_bytes=data.get("shown_bytes"),
            path=data.get("path"),
            range_start=data.get("range_start"),
            range_end=data.get("range_end"),
            exit_code=data.get("exit_code"),
            duration_ms=data.get("duration_ms"),
            stderr_summary=data.get("stderr_summary"),
            change_summary=data.get("change_summary"),
            artifact_ref=data.get("artifact_ref"),
            continuation=data.get("continuation"),
            semantic_success=data.get("semantic_success"),
            source=str(data.get("source") or "structured"),
            unsupported_blocks=tuple(data.get("unsupported_blocks") or ()),
        )


class OutputBuffer:
    """只读输出视图，翻页不改变模型消息或触发模型调用。"""

    def __init__(
        self,
        content: str,
        *,
        metadata: OutputMetadata | None = None,
        page_size: int = 40,
    ) -> None:
        self.content = content
        base_metadata = (
            OutputMetadata.from_value(metadata)
            if isinstance(metadata, (ToolOutputMetadata, dict))
            else metadata
        )
        if base_metadata is None:
            line_count = _count_content_lines(content)
            base_metadata = OutputMetadata(
                total_bytes=len(content.encode("utf-8")),
                total_lines=line_count,
                shown_lines=line_count,
            )
        authoritative = (
            metadata is not None
            and base_metadata.source != "legacy"
            and base_metadata.completeness is not None
        )
        if not authoritative:
            base_metadata = _infer_legacy_metadata(content, base_metadata)
        self.metadata = base_metadata
        self.page_size = max(1, page_size)
        self.page = 1
        self.artifact_path = self.metadata.artifact_path
        self._page_offsets: dict[int, int] = {1: 0}
        known_line_count = max(0, int(self.metadata.shown_lines))
        self._shown_line_count: int | None = (
            known_line_count if known_line_count or not self.content else None
        )

    @property
    def lines(self) -> list[str]:
        return self.content.splitlines()

    @property
    def truncated(self) -> bool:
        if self.metadata.completeness is not None:
            return self.metadata.completeness in {
                "truncated",
                "incomplete",
                "unsupported",
            }
        return self.metadata.truncated_by is not None

    def _content_line_count(self) -> int:
        if self._shown_line_count is None:
            self._shown_line_count = _count_content_lines(self.content)
        return self._shown_line_count

    def _page_start(self, page: int) -> int:
        page = max(1, int(page))
        known_page = max(index for index in self._page_offsets if index <= page)
        offset = self._page_offsets[known_page]
        while known_page < page:
            for _ in range(self.page_size):
                newline = self.content.find("\n", offset)
                if newline < 0:
                    offset = len(self.content)
                    break
                offset = newline + 1
            known_page += 1
            if offset < len(self.content):
                self._page_offsets[known_page] = offset
        return offset

    def _read_page(self, page: int) -> list[str]:
        """Read one page without materializing all output lines."""
        offset = self._page_start(page)
        result: list[str] = []
        while offset < len(self.content) and len(result) < self.page_size:
            newline = self.content.find("\n", offset)
            if newline < 0:
                result.append(self.content[offset:])
                break
            line = self.content[offset:newline]
            result.append(line[:-1] if line.endswith("\r") else line)
            offset = newline + 1
        return result

    @property
    def can_export(self) -> bool:
        """只有原始输出未在工具层丢弃时才允许导出。"""
        return not self.truncated or bool(
            self.metadata.artifact_path and Path(self.metadata.artifact_path).is_file()
        )

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(self._content_line_count() / self.page_size))

    @property
    def visible_lines(self) -> tuple[int, int]:
        start = (self.page - 1) * self.page_size
        return start + 1, min(self._content_line_count(), start + self.page_size)

    @property
    def current_page(self) -> list[str]:
        return self._read_page(self.page)

    @property
    def range_label(self) -> str:
        start, end = self.visible_lines
        total = self.metadata.total_lines or self._content_line_count()
        return f"行 {start}-{end}/{total}"

    @property
    def diagnostic(self) -> str:
        if not self.truncated:
            if self.metadata.completeness == "unknown":
                return f"{self.range_label} · 完整性未知"
            shown = self.metadata.shown_bytes
            size = (
                f"{shown}/{self.metadata.total_bytes} B"
                if shown is not None
                else f"{self.metadata.total_bytes} B"
            )
            return f"{self.range_label} · {size}"
        recovery = "可通过 artifact 恢复" if self.metadata.artifact_path else "无法恢复"
        return (
            f"{self.range_label} · {self.metadata.total_bytes} B · "
            f"不完整(按 {self.metadata.truncated_by or self.metadata.completeness} 截断,{recovery})"
        )

    def head_tail_preview(self, head: int = 12, tail: int = 12) -> list[str]:
        """返回有限首尾预览，避免默认展开大结果。"""
        lines = self.lines
        limit = max(1, head) + max(1, tail)
        if len(lines) <= limit:
            return list(lines)
        return [*lines[:head], "… 中间输出已折叠 …", *lines[-tail:]]

    def next_page(self) -> bool:
        if self.page >= self.page_count:
            return False
        self.page += 1
        return True

    def previous_page(self) -> bool:
        if self.page <= 1:
            return False
        self.page -= 1
        return True

    def export(self, path: str | Path) -> Path:
        """显式导出当前可恢复的原始输出。"""
        if not self.can_export:
            raise ValueError("原始输出已在工具层截断,无法恢复或导出")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = Path(self.metadata.artifact_path) if self.truncated else None
        if source is not None and source.is_file() and source.resolve() != target.resolve():
            target.write_bytes(source.read_bytes())
        else:
            target.write_text(self.content, encoding="utf-8")
        self.artifact_path = str(target)
        return target

    def cleanup(self) -> None:
        """清理当前导出的临时附件；不存在时保持幂等。"""
        if not self.artifact_path:
            return
        try:
            Path(self.artifact_path).unlink(missing_ok=True)
        finally:
            self.artifact_path = None


def _infer_truncation_marker(content: str) -> str | None:
    """识别工具适配器留下的截断提示；预览折叠提示不算工具截断。"""
    if re.search(r"(?:输出)?已截断|达到(?:字节|行数)?上限|条目超限", content):
        return "tool"
    return None


def _count_content_lines(content: str) -> int:
    """Count line boundaries without constructing a complete line list."""
    if not content:
        return 0
    count = content.count("\n")
    return count if content.endswith(("\n", "\r")) else count + 1


def _infer_legacy_metadata(content: str, base: OutputMetadata) -> OutputMetadata:
    """Infer old marker semantics only when no structured snapshot exists."""
    inferred = _infer_truncation_marker(content)
    line_marker = re.search(r"\[(\d+)-(\d+)/(\d+)\s*行\]", content)
    item_marker = re.search(r"仅显示前\s*(\d+)\s*条.*?共\s*(\d+)\s*条", content)
    shown_lines = base.shown_lines
    total_lines = base.total_lines
    if line_marker is not None:
        shown_lines = int(line_marker.group(2))
        total_lines = int(line_marker.group(3))
        if shown_lines < total_lines:
            inferred = inferred or "tool"
    elif item_marker is not None:
        shown_lines = int(item_marker.group(1))
        total_lines = int(item_marker.group(2))
        if shown_lines < total_lines:
            inferred = inferred or "tool"
    if inferred is None and shown_lines == base.shown_lines and total_lines == base.total_lines:
        return base
    return OutputMetadata(
        total_bytes=base.total_bytes,
        total_lines=total_lines,
        shown_lines=shown_lines,
        truncated_by=base.truncated_by or inferred,
        artifact_path=base.artifact_path,
        completeness="truncated" if base.truncated_by or inferred else base.completeness,
        shown_bytes=base.shown_bytes,
        path=base.path,
        range_start=base.range_start,
        range_end=base.range_end,
        exit_code=base.exit_code,
        duration_ms=base.duration_ms,
        stderr_summary=base.stderr_summary,
        change_summary=base.change_summary,
        artifact_ref=base.artifact_ref,
        continuation=base.continuation,
        semantic_success=base.semantic_success,
        source="legacy",
    )
