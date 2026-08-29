"""write 原子工具:创建新文件或完整覆盖已有文件,自动创建父目录,恒写 LF。

重构(design D5/D7;对应 spec「write」):
- 走 ``ops.mkdir`` + ``ops.write_bytes``,content 按 UTF-8 原样编码落盘——
  不经平台换行翻译(修掉 Windows 下 ``Path.write_text`` 的 ``\\n``→``\\r\\n``);
- 套 ``with_path_lock`` 串行化同路径并发写。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import GovernedText, resolve_to_cwd, with_path_lock

__all__ = ["WriteTool"]


class WriteArgs(BaseModel):
    file_path: str = Field(description="要写入的文件路径")
    content: str = Field(description="写入的完整内容(覆盖已有文件)")


class WriteTool(AtomicTool):
    name = "write"
    description = "创建新文件或完整覆盖已有文件;父目录不存在时自动创建;统一 LF 换行。"
    Args = WriteArgs

    def _invoke(self, args: WriteArgs) -> str:
        path = resolve_to_cwd(args.file_path, self._cwd)
        data = args.content.encode("utf-8")
        try:
            with with_path_lock(path):
                self._ops.mkdir(path.parent, parents=True)
                self._ops.write_bytes(path, data)
        except PermissionError:
            raise ValueError(f"没有写入权限: {path}")
        except OSError as exc:
            raise ValueError(f"写入失败 {path}: {exc}")
        return GovernedText(
            f"已写入 {path}({len(data)} 字节)",
            {
                "completeness": "complete",
                "total_bytes": len(data),
                "total_lines": len(args.content.splitlines()),
                "shown_bytes": len(data),
                "shown_lines": len(args.content.splitlines()),
                "path": str(path),
                "change_summary": f"wrote {len(data)} bytes",
                "source": "tool",
            },
        )
