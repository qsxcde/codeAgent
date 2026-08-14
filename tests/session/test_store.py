"""会话存储测试:JSONL 追加不重写、父级链回放、版本解析、并发写串行化、内存后端。"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from codeagent.core.messages import Message, ToolCall
from codeagent.session.store import (
    CURRENT_VERSION,
    CompactionEntry,
    JsonFileStore,
    MemoryStore,
)


def _store(tmp_path):
    return JsonFileStore(tmp_path / "sessions")


def test_create_and_header(tmp_path):
    store = _store(tmp_path)
    ref = store.create("s1", parent_session="s0", cwd="/w")
    assert ref.id == "s1" and ref.parent_session == "s0" and ref.cwd == "/w"
    assert store.get("s1") == ref
    assert store.get("nope") is None
    with pytest.raises(ValueError, match="已存在"):
        store.create("s1")
    # header 是首行且版本正确
    first = json.loads(
        (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first["type"] == "session" and first["version"] == CURRENT_VERSION


def test_append_never_rewrites_history(tmp_path):
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="a"))
    store.append_message("s1", Message(role="assistant", content="b"))
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + 2 条消息,历史不被重写


def test_load_messages_roundtrip_with_parent_chain(tmp_path):
    store = _store(tmp_path)
    store.create("s1")
    user = Message(role="user", content="hi")
    assistant = Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="bash", args={"command": "echo ok"})],
        parent_id=user.id,
    )
    tool = Message(role="tool", content="ok", tool_call_id="c1", parent_id=assistant.id)
    store.append_message("s1", user)
    store.append_message("s1", assistant)
    store.append_message("s1", tool)

    loaded = store.load_messages("s1")
    assert [m.role for m in loaded] == ["user", "assistant", "tool"]
    # 父级链保留(回放/回滚/分叉基础)
    assert loaded[1].parent_id == loaded[0].id
    assert loaded[2].parent_id == loaded[1].id
    # tool_calls 完整往返
    assert loaded[1].tool_calls[0].id == "c1"
    assert loaded[1].tool_calls[0].args == {"command": "echo ok"}
    # 消息 id 稳定(不重新分配)
    assert loaded[0].id == user.id


def test_compaction_entry_roundtrip(tmp_path):
    store = _store(tmp_path)
    store.create("s1")
    store.append_compaction(
        "s1",
        CompactionEntry(
            summary="用户要求读取 a.py",
            details={"readFiles": ["a.py"], "modifiedFiles": []},
        ),
    )
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    assert entry["type"] == "compaction" and entry["summary"].startswith("用户")
    assert entry["details"]["readFiles"] == ["a.py"]
    # 压缩记录不参与消息恢复
    assert store.load_messages("s1") == []


def test_version_mismatch_rejected(tmp_path):
    store = _store(tmp_path)
    store.create("s1")
    path = tmp_path / "sessions" / "s1.jsonl"
    path.write_text(
        json.dumps({"type": "session", "version": 999, "id": "s1"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="版本不兼容"):
        store.load_messages("s1")


def test_corrupt_file_rejected(tmp_path):
    store = _store(tmp_path)
    store.create("s1")
    path = tmp_path / "sessions" / "s1.jsonl"
    path.write_text('{"type": "session", "version": 1}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="损坏"):
        store.load_messages("s1")


def test_concurrent_appends_do_not_lose_lines(tmp_path):
    """并发 append 串行化(路径锁):全部消息落盘,行不互相覆盖。"""
    store = _store(tmp_path)
    store.create("s1")

    def append(i: int) -> None:
        store.append_message("s1", Message(role="user", content=f"m{i}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(50)))
    assert len(store.load_messages("s1")) == 50


def test_list_sessions_sorted(tmp_path):
    store = _store(tmp_path)
    store.create("s2")
    store.create("s1")
    ids = [r.id for r in store.list()]
    assert set(ids) == {"s1", "s2"}


def test_memory_store_semantics():
    store = MemoryStore()
    ref = store.create("m1", cwd="/w")
    assert store.get("m1") == ref
    msg = Message(role="user", content="hi")
    store.append_message("m1", msg)
    assert store.load_messages("m1")[0].id == msg.id
    with pytest.raises(ValueError, match="已存在"):
        store.create("m1")
    with pytest.raises(ValueError, match="不存在"):
        store.load_messages("ghost")
