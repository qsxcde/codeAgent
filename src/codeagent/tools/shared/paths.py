"""路径解析工具:所有工具统一经此解析相对路径。

职责(design 决策;对应 spec「路径解析」):
- ``resolve_to_cwd``:相对路径以注入 cwd 为基准,``~`` 展开,绝对路径直通;
  cwd 缺省回退进程启动目录;
- ``normalize_path``:剥离 ``@`` 前缀(CLI ``@file`` 习惯)、归一 Unicode 空格;
- ``format_posix``:统一正斜杠表示,模型看到的路径跨平台一致。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["normalize_path", "resolve_to_cwd", "format_posix"]


def normalize_path(path: str) -> Path:
    """标准化路径字符串:~ 展开、@ 前缀剥离、Unicode 空格归一。"""
    text = path.strip()
    if text.startswith("@"):
        text = text[1:]
    # NBSP / 窄空格 / 表意空格 → 普通空格(模型抄路径时常见)
    text = text.replace(" ", " ").replace(" ", " ").replace("　", " ")
    return Path(os.path.expanduser(text))


def resolve_to_cwd(path: str, cwd: str | Path | None) -> Path:
    """把用户给的路径解析为绝对路径。

    相对路径以注入的 ``cwd`` 为基准(缺省进程启动目录);``~`` 与绝对路径直通。
    不做符号链接解析(lexical normalize),避免工具行为依赖真实文件系统布局。
    """
    p = normalize_path(path)
    if p.is_absolute():
        return p
    base = Path(cwd).expanduser() if cwd else Path.cwd()
    return Path(os.path.abspath(base / p))


def format_posix(path: str | Path) -> str:
    """统一正斜杠表示(Windows 也输出 ``/``),供模型看到稳定的路径格式。"""
    return Path(path).as_posix()
