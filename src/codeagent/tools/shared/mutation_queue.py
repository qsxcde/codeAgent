"""按路径串行化写的互斥队列。

背景(core/nodes/tools.py):工具经 langchain 在线程池中并行执行(同一消息的
tool_call 用 asyncio.gather 调度),同一文件的并发写(如 write+edit)会竞态丢更新。

职责(design D7;对应 spec「并行写串行化」):
- 以路径为粒度上 ``threading.Lock``,只包写类工具(write/edit),读类不锁;
- 调用方必须先经 ``resolve_to_cwd`` 把路径解析为绝对路径,再传入本模块——
  锁按路径字符串为键,不同拼写会命中不同锁;
- 路径规模有限,锁表暂不做回收(design D7 注明)。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

__all__ = ["with_path_lock"]

#: 路径字符串 → 互斥锁。
_locks: dict[str, threading.Lock] = {}
#: 保护 _locks 增删的全局锁(仅建锁时争用)。
_guard = threading.Lock()


def _lock_for(path: str | Path) -> threading.Lock:
    key = str(path)
    lock = _locks.get(key)
    if lock is None:
        with _guard:
            lock = _locks.get(key)
            if lock is None:
                lock = threading.Lock()
                _locks[key] = lock
    return lock


@contextmanager
def with_path_lock(path: str | Path) -> Iterator[None]:
    """以 path 为粒度串行化临界区;同一进程内线程级互斥。"""
    lock = _lock_for(path)
    with lock:
        yield
