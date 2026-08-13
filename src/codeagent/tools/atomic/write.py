"""write 原子工具:创建新文件或完整覆盖已有文件,自动创建父目录。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool

__all__ = ["WriteTool"]


class WriteArgs(BaseModel):
    file_path: str = Field(description="要写入的文件路径")
    content: str = Field(description="写入的完整内容(覆盖已有文件)")


class WriteTool(AtomicTool):
    name = "write"
    description = "创建新文件或完整覆盖已有文件;父目录不存在时自动创建。"
    Args = WriteArgs

    def _invoke(self, args: WriteArgs) -> str:
        path = Path(args.file_path).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.content, encoding="utf-8")
        except PermissionError:
            raise ValueError(f"没有写入权限: {path}")
        except OSError as exc:
            raise ValueError(f"写入失败 {path}: {exc}")
        return f"已写入 {path}({len(args.content.encode('utf-8'))} 字节)"
