"""edit 原子工具:old_string → new_string 精确字符串替换,保留文件原始换行与 BOM。

对齐 Claude Code 的错误码语义(design.md D2):
- 找不到 old_string → 报"未找到匹配文本";
- 匹配多处且未 replace_all → 报"文本不唯一";
- 全程无状态:不维护读取缓存,不要求预先 Read。

重构(design D5/D7;对应 spec「edit」):
- CRLF/BOM 归一→匹配→还原写回:匹配在 LF 空间做,写回还原文件原始换行约定
  与 BOM,未触碰区域字节不变(修掉 Windows 下整文件换行被改写的缺陷);
- 套 ``with_path_lock`` 串行化同路径并发写;
- 保留「替换结果与原文相同则 no-change」判据。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import (
    detect_line_ending,
    normalize_to_lf,
    resolve_to_cwd,
    restore_line_endings,
    strip_bom,
    with_path_lock,
)

__all__ = ["EditTool"]


class EditArgs(BaseModel):
    file_path: str = Field(description="要修改的文件路径")
    old_string: str = Field(description="要被替换的原文(必须与文件内容精确一致)")
    new_string: str = Field(description="替换后的文本")
    replace_all: bool = Field(False, description="替换所有匹配项;为 False 时匹配多处会报错")


class EditTool(AtomicTool):
    name = "edit"
    description = "精确替换文件中的一段文本(old_string → new_string);匹配不到或不唯一时会报错;保留文件原始换行约定与 BOM。"
    Args = EditArgs

    def _invoke(self, args: EditArgs) -> str:
        path = resolve_to_cwd(args.file_path, self._cwd)
        if not self._ops.exists(path):
            raise ValueError(f"文件不存在: {path}")
        if not self._ops.is_file(path):
            raise ValueError(f"不是文件: {path}")

        # 整个「读-改-写」周期置于路径锁内:仅锁写回会让并发编辑在「读」上竞争,
        # 后写覆盖先写(design D7;spec「并行写串行化」)。
        try:
            with with_path_lock(path):
                raw = self._ops.read_bytes(path)
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError(f"文件不是 UTF-8 文本,无法编辑: {path}")

                # CRLF/BOM 归一:匹配在 LF 空间做,写回还原原始约定(design D5)。
                text, bom = strip_bom(content)
                ending = detect_line_ending(text)
                normalized = normalize_to_lf(text)

                old = args.old_string
                if not old:
                    raise ValueError(f"old_string 不能为空: {path}")
                count = normalized.count(old)
                if count == 0:
                    raise ValueError(
                        f"未找到匹配文本(请确认 old_string 与文件内容精确一致): {path}"
                    )
                if count > 1 and not args.replace_all:
                    raise ValueError(
                        f"old_string 在文件中出现 {count} 次,不唯一;"
                        f"如需全部替换请设置 replace_all=true,或扩大匹配上下文: {path}"
                    )

                updated = normalized.replace(old, normalize_to_lf(args.new_string))
                # no-change 判据:替换后与归一空间原文相同 → 无实际变更(design D5)。
                if updated == normalized:
                    raise ValueError(f"未产生变更(替换结果与原文相同): {path}")

                final = bom + restore_line_endings(updated, ending)
                self._ops.write_bytes(path, final.encode("utf-8"))
        except PermissionError:
            raise ValueError(f"没有写入权限: {path}")
        except OSError as exc:
            raise ValueError(f"写入失败 {path}: {exc}")
        return f"已替换 {count} 处: {path}"
