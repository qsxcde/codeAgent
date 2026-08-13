"""edit 原子工具:old_string → new_string 精确字符串替换。

对齐 Claude Code 的错误码语义(design.md D2):
- 找不到 old_string → 报"未找到匹配文本"(错误码 8);
- 匹配多处且未 replace_all → 报"文本不唯一"(错误码 9);
- 全程无状态:不维护读取缓存,不要求预先 Read(评审 R1 消解结论)。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool

__all__ = ["EditTool"]


class EditArgs(BaseModel):
    file_path: str = Field(description="要修改的文件路径")
    old_string: str = Field(description="要被替换的原文(必须与文件内容精确一致)")
    new_string: str = Field(description="替换后的文本")
    replace_all: bool = Field(False, description="替换所有匹配项;为 False 时匹配多处会报错")


class EditTool(AtomicTool):
    name = "edit"
    description = "精确替换文件中的一段文本(old_string → new_string);匹配不到或不唯一时会报错。"
    Args = EditArgs

    def _invoke(self, args: EditArgs) -> str:
        path = Path(args.file_path).expanduser()
        if not path.exists():
            raise ValueError(f"文件不存在: {path}")
        if not path.is_file():
            raise ValueError(f"不是文件: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except PermissionError:
            raise ValueError(f"没有读取权限: {path}")
        except UnicodeDecodeError:
            raise ValueError(f"文件不是 UTF-8 文本,无法编辑: {path}")
        except OSError as exc:
            raise ValueError(f"读取失败 {path}: {exc}")

        old = args.old_string
        if not old:
            raise ValueError(f"old_string 不能为空: {path}")
        count = content.count(old)
        if count == 0:
            raise ValueError(f"未找到匹配文本(请确认 old_string 与文件内容精确一致): {path}")
        if count > 1 and not args.replace_all:
            raise ValueError(
                f"old_string 在文件中出现 {count} 次,不唯一;"
                f"如需全部替换请设置 replace_all=true,或扩大匹配上下文: {path}"
            )

        updated = content.replace(old, args.new_string)
        try:
            path.write_text(updated, encoding="utf-8")
        except PermissionError:
            raise ValueError(f"没有写入权限: {path}")
        except OSError as exc:
            raise ValueError(f"写入失败 {path}: {exc}")
        return f"已替换 {count} 处: {path}"
