"""输出截断工具:字节+行双上限,头/尾截断。

职责(对应 spec「输出截断」):
- 所有工具统一经此截断输出,任一上限先到即截,截断必标记;
- ``truncate_head`` 保留开头(read/grep/find/ls),``truncate_tail`` 保留末尾(bash,
  超时/报错信息通常在末尾,design D6)。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_LINES",
    "TruncationResult",
    "truncate_head",
    "truncate_tail",
]

#: 默认单次输出的字节上限。
DEFAULT_MAX_BYTES = 30_000
#: 默认单次输出的行数上限。
DEFAULT_MAX_LINES = 2000


@dataclass
class TruncationResult:
    """截断元信息,供调用方构造截断标记。"""

    #: 是否发生截断。
    truncated: bool = False
    #: 触发的上限:"lines" | "bytes",None 表示未截断。
    truncated_by: str | None = None
    #: 截断前总行数。
    total_lines: int = 0
    #: 截断后保留行数(近似:字节截断后不再精确到行)。
    shown_lines: int = 0
    #: 原文总字节数(UTF-8)。
    total_bytes: int = 0


def _count_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _byte_cut_head(text: str, max_bytes: int) -> tuple[str, bool]:
    """按字节上限截开头,保证不切断多字节字符。"""
    if _count_bytes(text) <= max_bytes:
        return text, False
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore"), True


def _byte_cut_tail(text: str, max_bytes: int) -> tuple[str, bool]:
    """按字节上限截末尾,保证不切断多字节字符。"""
    if _count_bytes(text) <= max_bytes:
        return text, False
    return text.encode("utf-8")[-max_bytes:].decode("utf-8", errors="ignore"), True


def truncate_head(
    text: str, max_lines: int = DEFAULT_MAX_LINES, max_bytes: int = DEFAULT_MAX_BYTES
) -> tuple[str, TruncationResult]:
    """保留开头:先按行截,再按字节截。返回 (截断后文本, 元信息)。"""
    lines = text.splitlines()
    total_lines = len(lines)
    truncated_by: str | None = None
    shown_lines = total_lines
    if total_lines > max_lines:
        lines = lines[:max_lines]
        shown_lines = max_lines
        truncated_by = "lines"
    body = "\n".join(lines)
    body, byte_cut = _byte_cut_head(body, max_bytes)
    if byte_cut:
        truncated_by = "bytes"
    return body, TruncationResult(
        truncated=truncated_by is not None,
        truncated_by=truncated_by,
        total_lines=total_lines,
        shown_lines=shown_lines,
        total_bytes=_count_bytes(text),
    )


def truncate_tail(
    text: str, max_lines: int = DEFAULT_MAX_LINES, max_bytes: int = DEFAULT_MAX_BYTES
) -> tuple[str, TruncationResult]:
    """保留末尾:先按行截,再按字节截。返回 (截断后文本, 元信息)。"""
    lines = text.splitlines()
    total_lines = len(lines)
    truncated_by: str | None = None
    shown_lines = total_lines
    if total_lines > max_lines:
        lines = lines[-max_lines:]
        shown_lines = max_lines
        truncated_by = "lines"
    body = "\n".join(lines)
    body, byte_cut = _byte_cut_tail(body, max_bytes)
    if byte_cut:
        truncated_by = "bytes"
    return body, TruncationResult(
        truncated=truncated_by is not None,
        truncated_by=truncated_by,
        total_lines=total_lines,
        shown_lines=shown_lines,
        total_bytes=_count_bytes(text),
    )
