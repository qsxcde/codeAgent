"""会话树纯函数测试(session-tree):fork 链组织 / 孤儿独立根 / 排序 / 环诊断。"""

from codeagent.session.store import SessionRef
from codeagent.session.tree import SessionNode, build_tree


def _ref(session_id: str, parent: str | None = None, timestamp: str = "t", title: str = "") -> SessionRef:
    return SessionRef(
        id=session_id, timestamp=timestamp, cwd="/", parent_session=parent, title=title or session_id
    )


def _flat(node: SessionNode) -> list[str]:
    """树 → 前序 id 列表(测试断言结构)。"""
    return [node.ref.id] + [child_id for child in node.children for child_id in _flat(child)]


def test_build_tree_organizes_fork_chain():
    """A→B→C fork 链:单个根 A,B 挂 A 下,C 挂 B 下。"""
    refs = [_ref("a"), _ref("b", parent="a"), _ref("c", parent="b")]
    roots = build_tree(refs)
    assert len(roots) == 1
    assert _flat(roots[0]) == ["a", "b", "c"]


def test_build_tree_multiple_branches_sorted():
    """A 的两个分支 B/C:同级按时间排序。"""
    refs = [_ref("a"), _ref("b", parent="a", timestamp="t1"), _ref("c", parent="a", timestamp="t2")]
    roots = build_tree(refs)
    assert [child.ref.id for child in roots[0].children] == ["b", "c"]


def test_build_tree_orphan_as_independent_root():
    """孤儿(父不存在)作为独立根,不丢失。"""
    refs = [_ref("a"), _ref("b", parent="ghost")]
    roots = build_tree(refs)
    assert {root.ref.id for root in roots} == {"a", "b"}
    assert all(root.children == [] for root in roots)


def test_build_tree_deep_chain_and_multi_root():
    """A→B→C 链 + 独立根 D:两个根,深度不受限。"""
    refs = [_ref("a"), _ref("b", parent="a"), _ref("c", parent="b"), _ref("d")]
    roots = build_tree(refs)
    assert {root.ref.id for root in roots} == {"a", "d"}
    chain = next(r for r in roots if r.ref.id == "a")
    assert _flat(chain) == ["a", "b", "c"]


def test_build_tree_empty():
    """空列表 → 空树。"""
    assert build_tree([]) == []


def test_build_tree_cycle_downgraded_to_root_with_diagnostic():
    """parentSession 环:环上节点降级为独立根,on_cycle 收到诊断。"""
    refs = [_ref("a", parent="b"), _ref("b", parent="a")]
    diagnosed: list[str] = []
    roots = build_tree(refs, on_cycle=diagnosed.append)
    # 两个节点都是根(环无法挂接),且至少一个触发环诊断。
    assert {root.ref.id for root in roots} == {"a", "b"}
    assert diagnosed  # 环上节点被诊断
