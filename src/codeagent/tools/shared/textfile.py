"""文本编码工具:BOM / 换行 归一→还原。

职责(design D5;对应 spec「edit 保留原始换行约定」):
- edit 的匹配在 LF 归一空间做,写回时还原文件原始换行约定与 BOM,
  未触碰区域字节不变(修掉 Windows 下整文件换行被改写的缺陷);
- ``strip_bom`` / ``detect_line_ending`` / ``normalize_to_lf`` / ``restore_line_endings``
  是本项目唯一实现的换行/BOM 处理,勿另写一份。
"""

from __future__ import annotations

__all__ = ["strip_bom", "detect_line_ending", "normalize_to_lf", "restore_line_endings"]

BOM_UTF8 = "﻿"


def strip_bom(text: str) -> tuple[str, str]:
    """分离文本开头的 UTF-8 BOM,返回 ``(去 BOM 文本, BOM)``。"""
    if text.startswith(BOM_UTF8):
        return text[1:], BOM_UTF8
    return text, ""


def detect_line_ending(text: str) -> str:
    """检测文件主要使用的换行符:优先 CRLF,其次 CR,缺省 LF。"""
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def normalize_to_lf(text: str) -> str:
    """CRLF / CR 统一转 LF(匹配空间)。先处理 CRLF 再处理 CR,避免 ``\\r\\n`` 被二次替换。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore_line_endings(text: str, ending: str) -> str:
    """把 LF 归一空间的内容还原为指定换行。``ending`` 为 ``\\n`` 时原样返回。"""
    if ending == "\n":
        return text
    return text.replace("\n", ending)
