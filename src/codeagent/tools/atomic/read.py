"""read 原子工具:读取文件内容,支持行范围分页与字节+行双上限截断。

重构(design):走注入的 ``FsOps`` + ``resolve_to_cwd``,分页与二进制前缀行为保留;
输出经 ``truncate_head`` 统一字节/行双上限(对应 spec「read」)。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import (
    DEFAULT_MAX_LINES,
    GovernedText,
    resolve_to_cwd,
    truncate_head,
)

__all__ = ["ReadTool", "DEFAULT_MAX_LINES", "BINARY_PREVIEW_BYTES"]

#: 二进制/非 UTF-8 文件返回的可读前缀字节数。
BINARY_PREVIEW_BYTES = 4096


class ReadArgs(BaseModel):
    file_path: str = Field(description="要读取的文件路径")
    offset: int = Field(0, description="起始行号(0 基),跳过前面的行")
    limit: int | None = Field(None, description="最多读取的行数,缺省 2000")


class ReadTool(AtomicTool):
    name = "read"
    description = "读取文件内容;支持 offset/limit 分页,大文件自动截断并标记。"
    Args = ReadArgs

    def _invoke(self, args: ReadArgs) -> str:
        path = resolve_to_cwd(args.file_path, self._cwd)
        if not self._ops.exists(path):
            raise ValueError(f"文件不存在: {path}")
        if not self._ops.is_file(path):
            raise ValueError(f"不是文件: {path}")

        try:
            raw = self._ops.read_bytes(path)
        except PermissionError:
            raise ValueError(f"没有读取权限: {path}")
        except OSError as exc:
            raise ValueError(f"读取失败 {path}: {exc}")

        # 二进制 / 非 UTF-8 安全处理:返回可读前缀并标记。
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            preview = raw[: min(BINARY_PREVIEW_BYTES, self.output_max_bytes)].decode(
                "utf-8", errors="replace"
            )
            content = (
                f"[二进制或非 UTF-8 文件,共 {len(raw)} 字节,仅显示可读前缀]\n"
                f"{preview}"
            )
            return GovernedText(
                content,
                {
                    "completeness": "unsupported",
                    "total_bytes": len(raw),
                    "total_lines": len(raw.splitlines()),
                    "shown_bytes": len(preview.encode("utf-8")),
                    "shown_lines": len(preview.splitlines()),
                    "truncated_by": "binary_preview",
                    "path": str(path),
                    "source": "tool",
                },
            )

        lines = text.splitlines()
        total = len(lines)
        start = args.offset
        if start < 0:
            raise ValueError(f"offset 不能为负: {start}")
        if start >= total and not (total == 0 and start == 0):
            raise ValueError(f"offset {start} 超出文件行数 {total}")
        requested_limit = args.limit if args.limit is not None else DEFAULT_MAX_LINES
        limit = min(requested_limit, self.output_max_lines)
        limited = limit < total - start
        end = start + min(limit, total - start)
        body = "\n".join(lines[start:end])
        # 字节+行双上限(行上限与 limit 相同,已在上方切片;这里主要兜字节)
        body, trunc = truncate_head(
            body, max_lines=limit, max_bytes=self.output_max_bytes
        )

        parts = [f"[{start + 1}-{end}/{total} 行]" if limited else f"[{total} 行]"]
        parts.append(body)
        if limited or trunc.truncated:
            parts.append(f"[已截断,共 {total} 行,可通过 offset={end} 继续读取]")
        content = "\n".join(parts)
        shown_bytes = len(body.encode("utf-8"))
        shown_lines = len(body.splitlines())
        return GovernedText(
            content,
            {
                "completeness": "truncated" if limited or trunc.truncated else "complete",
                "total_bytes": len(raw),
                "total_lines": total,
                "shown_bytes": shown_bytes,
                "shown_lines": shown_lines,
                "truncated_by": "tool_lines" if limited else ("tool_bytes" if trunc.truncated else None),
                "path": str(path),
                "range_start": start,
                "range_end": end,
                "continuation": f"offset={end}" if limited or trunc.truncated else None,
                "source": "tool",
            },
        )
