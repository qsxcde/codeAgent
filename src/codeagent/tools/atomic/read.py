"""read 原子工具:读取文件内容,支持行范围分页与截断标记。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool

__all__ = ["ReadTool"]

#: 默认单次读取的行数上限,防止大文件撑爆上下文。
DEFAULT_MAX_LINES = 2000
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
        path = Path(args.file_path).expanduser()
        if not path.exists():
            raise ValueError(f"文件不存在: {path}")
        if not path.is_file():
            raise ValueError(f"不是文件: {path}")

        try:
            raw = path.read_bytes()
        except PermissionError:
            raise ValueError(f"没有读取权限: {path}")
        except OSError as exc:
            raise ValueError(f"读取失败 {path}: {exc}")

        # 二进制 / 非 UTF-8 安全处理:返回可读前缀并标记。
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            preview = raw[:BINARY_PREVIEW_BYTES].decode("utf-8", errors="replace")
            return (
                f"[二进制或非 UTF-8 文件,共 {len(raw)} 字节,仅显示可读前缀]\n"
                f"{preview}"
            )

        lines = text.splitlines()
        total = len(lines)
        start = args.offset
        if start < 0:
            raise ValueError(f"offset 不能为负: {start}")
        if start >= total and not (total == 0 and start == 0):
            raise ValueError(f"offset {start} 超出文件行数 {total}")
        limit = args.limit if args.limit is not None else DEFAULT_MAX_LINES
        limited = limit < total - start
        end = start + min(limit, total - start)
        body = lines[start:end]

        parts = [f"[{start + 1}-{end}/{total} 行]" if limited else f"[{total} 行]"]
        parts.extend(body)
        if limited:
            parts.append(f"[已截断,共 {total} 行,可通过 offset={end} 继续读取]")
        return "\n".join(parts)
