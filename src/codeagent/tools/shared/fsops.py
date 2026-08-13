"""FsOps 协议:工具层唯一的文件系统抽象缝。

分层约束:本模块供 tools/ 内部使用,禁止 import core/session/ai;不 import langchain。

职责(design D1):
- 工具逻辑只认识 ``FsOps``,不直接触碰文件系统 → 测试可注入内存/临时实现,免 chdir;
- ``walk`` 采用 os.walk 风格 ``(root, dirs, files)`` 三元组:调用方在遍历中
  ``dirs[:]`` 剪枝(跳过噪声目录),让「跳过策略」留在工具层而非泄漏进 FsOps,
  测试也能注入假目录树;
- 将来接远程文件系统(SSH)只需换一个实现,工具零改动。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Protocol

__all__ = ["FsOps", "LocalFsOps"]


class FsOps(Protocol):
    """工具可用的最小文件操作面。"""

    def read_bytes(self, path: Path) -> bytes: ...
    def write_bytes(self, path: Path, data: bytes) -> None: ...
    def exists(self, path: Path) -> bool: ...
    def is_file(self, path: Path) -> bool: ...
    def is_dir(self, path: Path) -> bool: ...
    def mkdir(self, path: Path, parents: bool = True) -> None: ...
    def readdir(self, path: Path) -> list[str]: ...
    def walk(self, path: Path) -> Iterator[tuple[Path, list[str], list[str]]]: ...


class LocalFsOps:
    """本地文件系统实现:薄封装 pathlib/os。"""

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes(self, path: Path, data: bytes) -> None:
        path.write_bytes(data)

    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def mkdir(self, path: Path, parents: bool = True) -> None:
        path.mkdir(parents=parents, exist_ok=True)

    def readdir(self, path: Path) -> list[str]:
        return [entry.name for entry in os.scandir(path)]

    def walk(self, path: Path) -> Iterator[tuple[Path, list[str], list[str]]]:
        for root, dirs, files in os.walk(path):
            yield Path(root), dirs, files
