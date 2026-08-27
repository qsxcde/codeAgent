"""文件系统测试资源。"""

from __future__ import annotations

from pathlib import Path

import pytest


class InMemoryFsOps:
    """内存版 FsOps,避免原子文件工具测试依赖真实文件系统。"""

    def __init__(self) -> None:
        self.files: dict[Path, bytes] = {}
        self.dirs: set[Path] = set()

    def read_bytes(self, path: Path) -> bytes:
        return self.files[path]

    def write_bytes(self, path: Path, data: bytes) -> None:
        self.files[path] = data

    def exists(self, path: Path) -> bool:
        return path in self.files or path in self.dirs

    def is_file(self, path: Path) -> bool:
        return path in self.files

    def is_dir(self, path: Path) -> bool:
        return path in self.dirs

    def mkdir(self, path: Path, parents: bool = True) -> None:
        self.dirs.add(path)

    def readdir(self, path: Path) -> list[str]:
        names = {p.name for p in self.files if p.parent == path}
        names |= {d.name for d in self.dirs if d.parent == path}
        return sorted(names)

    def walk(self, path: Path):
        roots = [path] + sorted(d for d in self.dirs if d != path and path in d.parents)
        for root in roots:
            dirs = sorted(d.name for d in self.dirs if d.parent == root and d != root)
            files = sorted(f.name for f in self.files if f.parent == root)
            yield root, dirs, files


@pytest.fixture
def memory_fsops() -> InMemoryFsOps:
    """内存版 FsOps,供 read/write/edit/find/grep/ls 注入测试。"""
    return InMemoryFsOps()
