"""registry behavior tests."""

from tests.tools.atomic.fixtures import *  # noqa: F401,F403


def test_make_tools_returns_all_atomic_tools():
    tools = create_tools()
    assert isinstance(tools, list)
    assert len(tools) == 8
    names = {t.name for t in tools}
    assert names == {"read", "write", "edit", "bash", "grep", "find", "ls", "skill"}
    from codeagent.tools.base import AtomicTool

    assert all(isinstance(t, AtomicTool) for t in tools)



def test_make_tools_offline(tmp_path):
    """无网络/无密钥副作用。"""
    tools = create_tools()
    assert tools  # 仅断言可装配



def test_dangerous_patterns_nonempty():
    assert DANGEROUS_PATTERNS

