"""工具结果的非持久化统计、预览分页和显式导出模型。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["OutputMetadata", "OutputBuffer"]


@dataclass(frozen=True)
class OutputMetadata:
    """工具层输出统计；不会写入会话消息。"""

    total_bytes: int = 0
    total_lines: int = 0
    shown_lines: int = 0
    truncated_by: str | None = None
    artifact_path: str | None = None


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
        base_metadata = metadata or OutputMetadata(
            total_bytes=len(content.encode("utf-8")),
            total_lines=len(content.splitlines()),
            shown_lines=len(content.splitlines()),
        )
        inferred = _infer_truncation_marker(content)
        line_marker = re.search(r"\[(\d+)-(\d+)/(\d+)\s*行\]", content)
        item_marker = re.search(
            r"仅显示前\s*(\d+)\s*条.*?共\s*(\d+)\s*条", content
        )
        shown_lines = base_metadata.shown_lines
        total_lines = base_metadata.total_lines
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
        if (
            base_metadata.truncated_by is None
            and inferred is not None
            or shown_lines != base_metadata.shown_lines
            or total_lines != base_metadata.total_lines
        ):
            base_metadata = OutputMetadata(
                total_bytes=base_metadata.total_bytes,
                total_lines=total_lines,
                shown_lines=shown_lines,
                truncated_by=base_metadata.truncated_by or inferred,
                artifact_path=base_metadata.artifact_path,
            )
        self.metadata = base_metadata
        self.page_size = max(1, page_size)
        self.page = 1
        self.artifact_path = self.metadata.artifact_path

    @property
    def lines(self) -> list[str]:
        return self.content.splitlines()

    @property
    def truncated(self) -> bool:
        return self.metadata.truncated_by is not None

    @property
    def can_export(self) -> bool:
        """只有原始输出未在工具层丢弃时才允许导出。"""
        return not self.truncated

    @property
    def page_count(self) -> int:
        return max(1, math.ceil(len(self.lines) / self.page_size))

    @property
    def visible_lines(self) -> tuple[int, int]:
        start = (self.page - 1) * self.page_size
        return start + 1, min(len(self.lines), start + self.page_size)

    @property
    def current_page(self) -> list[str]:
        start = (self.page - 1) * self.page_size
        return self.lines[start : start + self.page_size]

    @property
    def range_label(self) -> str:
        start, end = self.visible_lines
        total = self.metadata.total_lines or len(self.lines)
        return f"行 {start}-{end}/{total}"

    @property
    def diagnostic(self) -> str:
        if not self.truncated:
            return f"{self.range_label} · {self.metadata.total_bytes} B"
        return (
            f"{self.range_label} · {self.metadata.total_bytes} B · "
            f"不完整(工具层按 {self.metadata.truncated_by} 截断,无法恢复)"
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
