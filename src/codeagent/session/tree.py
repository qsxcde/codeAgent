"""session/tree.py:会话树视图纯函数(session-tree,F-23 剩余)。

把 ``SessionStore.list()`` 返回的平铺会话列表组织为 fork 树:
- 边 = ``SessionRef.parent_session``(v0.2 fork 已落盘);
- 孤儿(父会话 id 不在列表)作为独立根,不丢失;
- 同级分支按会话时间排序(与 list 一致);
- 纯函数、零 I/O、零跨层,可离线测试。

分层约束:仅依赖同层 ``session/store``,不 import core/ai/tools/config。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from codeagent.session.store import SessionRef

__all__ = ["SessionNode", "build_tree"]


@dataclass
class SessionNode:
    """会话树节点:会话元数据 + 其子分支(按时间序)。"""

    ref: SessionRef
    children: list["SessionNode"] = field(default_factory=list)


def build_tree(
    refs: list[SessionRef],
    *,
    on_cycle: Callable[[str], None] | None = None,
) -> list[SessionNode]:
    """把平铺会话列表组织为 fork 树,返回根节点列表。

    - 孤儿(父 id 不在列表)作为独立根;
    - 同级分支按 ``(timestamp, id)`` 排序(与 store.list 一致);
    - 循环防护:检测到 ``parentSession`` 环时对该节点调 ``on_cycle``
      (缺省忽略),并把环上节点降级为独立根,避免死递归。
    """
    if not refs:
        return []
    by_id = {ref.id: ref for ref in refs}
    # 先按时间排序,保证 children 追加即有序(同级分支时间序)。
    ordered = sorted(refs, key=lambda r: (r.timestamp, r.id))
    children_of: dict[str, list[SessionRef]] = {ref.id: [] for ref in refs}
    roots: list[SessionRef] = []
    cyclic: set[str] = set()

    def is_cyclic(session_id: str) -> bool:
        """沿 parentSession 链检测环(走到已知根/未知父即无环)。"""
        seen: set[str] = set()
        current = session_id
        while current in by_id:
            if current in seen:
                return True
            seen.add(current)
            parent = by_id[current].parent_session
            if parent is None:
                return False
            current = parent
        return False

    for ref in ordered:
        parent_id = ref.parent_session
        if parent_id is not None and parent_id in by_id and not is_cyclic(ref.id):
            children_of[parent_id].append(ref)
        else:
            roots.append(ref)
            if parent_id is not None and is_cyclic(ref.id):
                cyclic.add(ref.id)

    for session_id in cyclic:
        if on_cycle is not None:
            on_cycle(session_id)

    def build(ref: SessionRef) -> SessionNode:
        node = SessionNode(ref=ref)
        node.children = [build(child) for child in children_of[ref.id]]
        return node

    return [build(ref) for ref in roots]
