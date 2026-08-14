"""pytest 共享夹具。"""

from pathlib import Path

import pytest


class InMemoryFsOps:
    """内存版 FsOps:零文件系统依赖,供注入测试(design D1 的可测性收益)。

    ``walk`` 以 path 为根做先序遍历,产出 ``(root Path, [dirs], [files])``,
    与 ``LocalFsOps.walk``(os.walk 风格)一致,find/grep 注入测试可用。
    """

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
    """内存版 FsOps,完全离线,供注入测试。"""
    return InMemoryFsOps()


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """把 ensure_config_files 的写入位置重定向到临时目录。

    避免走启动路径的测试(container/session_client)在用户真实
    ``~/.codeagent`` 里生成模板文件;读取路径(Settings/ModelStore)
    仍只读,无副作用。
    """
    import codeagent.app.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".codeagent")
