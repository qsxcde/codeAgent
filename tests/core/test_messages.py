"""core 消息层测试:uuid7 格式/有序、消息归约(归属/删除/替换)。"""

from codeagent.core.messages import (
    Message,
    ToolCall,
    ToolResult,
    attach_tool_results,
    new_id,
    remove_by_id,
    replace_or_append,
)


def test_uuid7_format_and_uniqueness():
    """uuid7 为标准 UUID 字符串(8-4-4-4-12),多次调用全局唯一。"""
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000
    for value in ids:
        parts = value.split("-")
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]
        assert all(int(p, 16) >= 0 for p in parts)
        # 版本位 = 7(第 13 个十六进制字符)
        assert value[14] == "7"


def test_uuid7_time_ordered():
    """uuid7 时间前缀有序:先后生成的两个 id,前者时间戳字段 <= 后者。"""
    a = new_id()
    b = new_id()
    # 时间戳 = 前 48 位(去掉连字符后的前 12 个十六进制字符)
    ts = lambda v: int(v.replace("-", "")[:12], 16)  # noqa: E731
    assert ts(a) <= ts(b)


def test_message_auto_assigns_id_and_parent():
    """Message 构造自动分配 uuid7;parent_id 显式传入保留。"""
    parent = Message(role="user", content="hi")
    child = Message(role="assistant", content="ok", parent_id=parent.id)
    assert parent.id
    assert child.id != parent.id
    assert child.parent_id == parent.id


def test_attach_tool_results_orders_by_tool_call_list():
    """工具结果按 assistant.tool_calls 列表序归属(并行 gather 保序语义)。"""
    messages = [
        Message(role="user", content="u"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="c1", name="bash", args={"command": "echo a"}),
                ToolCall(id="c2", name="bash", args={"command": "echo b"}),
            ],
        ),
    ]
    # 结果以乱序返回:归属仍按 calls 顺序落盘
    attach_tool_results(
        messages,
        [
            ToolResult("c2", "result-b"),
            ToolResult("c1", "result-a"),
        ],
    )
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant", "tool", "tool"]
    assert messages[2].tool_call_id == "c1" and messages[2].content == "result-a"
    assert messages[3].tool_call_id == "c2" and messages[3].content == "result-b"
    # 归属的 tool 消息 parent 指向 assistant
    assert messages[2].parent_id == messages[1].id


def test_attach_tool_results_unknown_id_appended():
    """未知 tool_call_id 的结果追加到列表尾部(防御,不丢失)。"""
    messages = [Message(role="user", content="u")]
    attach_tool_results(messages, [ToolResult("ghost", "x")])
    assert messages[-1].role == "tool" and messages[-1].tool_call_id == "ghost"


def test_remove_by_id_and_replace():
    """按 id 删除与同 id 替换(归约语义①:RemoveMessage 等价)。"""
    m1 = Message(role="user", content="a")
    m2 = Message(role="assistant", content="b")
    messages = [m1, m2]

    remaining = remove_by_id(messages, {m1.id})
    assert [m.id for m in remaining] == [m2.id]
    assert len(messages) == 2  # 原列表不被修改

    replace_or_append(messages, Message(role="assistant", content="b2", id=m2.id))
    assert messages[1].content == "b2"
    replace_or_append(messages, Message(role="user", content="c"))
    assert len(messages) == 3
