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


# -- session-manager change:元数据 / meta entry / 标题派生 --------------------


def test_header_model_effort_roundtrip(tmp_path):
    """header 可选字段 model/effort:创建时写入,读侧透传(design D4)。"""
    store = _store(tmp_path)
    ref = store.create("s1", model="deepseek-v4-flash", effort="high")
    assert ref.model == "deepseek-v4-flash" and ref.effort == "high"
    got = store.get("s1")
    assert got.model == "deepseek-v4-flash" and got.effort == "high"
    first = json.loads(
        (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first["model"] == "deepseek-v4-flash" and first["effort"] == "high"


def test_meta_entry_last_write_wins(tmp_path):
    """meta 后写覆盖:同 key 取最近一次 value(design D2,对齐 Pi session_info)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.set_meta("s1", "name", "第一次")
    store.set_meta("s1", "name", "重构 auth 模块")
    assert store.get_meta("s1", "name") == "重构 auth 模块"
    assert store.get_meta("s1", "nope") is None
    # meta 是独立 entry 追加,不参与消息恢复
    assert store.load_messages("s1") == []
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + 2 条 meta


def test_title_derived_from_first_user_message(tmp_path):
    """默认派生:首条用户消息截断 20 字符(design D3)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="我们来重构一下那个核心解析模块让性能更好吧"))
    store.append_message("s1", Message(role="assistant", content="好的"))
    title = store.get("s1").title
    assert title.startswith("我们来重构一下那个核心解析模块让性能") and title.endswith("…")
    assert len(title) == 21  # 20 字符 + 省略号


def test_title_prefers_explicit_name(tmp_path):
    """显式命名优先于派生标题(design D3,对齐 Pi /name)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="首条用户消息"))
    assert store.get("s1").title == "首条用户消息"
    store.set_meta("s1", "name", "重构 auth 模块")
    assert store.get("s1").title == "重构 auth 模块"


def test_legacy_file_without_model_effort(tmp_path):
    """旧格式文件(无 model/effort 键)向后兼容:读侧默认空(design D7)。"""
    store = _store(tmp_path)
    path = tmp_path / "sessions" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"type": "session", "version": 1, "id": "s1", "timestamp": "t", "cwd": "/w"}
        )
        + "\n"
        + json.dumps({"type": "message", "id": "m1", "parentId": None, "role": "user", "content": "hi"})
        + "\n",
        encoding="utf-8",
    )
    ref = store.get("s1")
    assert ref.model == "" and ref.effort == ""
    assert ref.title == "hi"
    assert store.load_messages("s1")[0].content == "hi"


def test_unknown_entry_types_ignored(tmp_path):
    """未知 entry 类型(未来格式演进)被读侧忽略,不破坏解析。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="hi"))
    path = tmp_path / "sessions" / "s1.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "future_entry", "data": 1}) + "\n")
    assert store.get("s1").title == "hi"
    assert store.load_messages("s1")[0].content == "hi"
    assert store.get_meta("s1", "name") is None


def test_model_change_entry_overrides_header(tmp_path):
    """model_change entry 追加式写入,读侧后写覆盖 header(热切换持久化)。"""
    store = _store(tmp_path)
    store.create("s1", model="a", effort="low")
    store.append_model_change("s1", model="b", effort="high")
    ref = store.get("s1")
    assert ref.model == "b" and ref.effort == "high"
    # 空字段不覆盖:只传 model 时 effort 保留上一值
    store.append_model_change("s1", model="c")
    ref = store.get("s1")
    assert ref.model == "c" and ref.effort == "high"
    # 文件为追加式:历史 entry 未被改写
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + 2 次 model_change


def test_model_change_legacy_file_without_header_config(tmp_path):
    """旧文件(header 无 model/effort)+ model_change:读侧取 entry 值。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_model_change("s1", model="b", effort="high")
    ref = store.get("s1")
    assert ref.model == "b" and ref.effort == "high"


def test_memory_store_model_change():
    """MemoryStore 与文件后端同语义:model_change 后写覆盖 create 值。"""
    store = MemoryStore()
    store.create("m1", model="a", effort="low")
    store.append_model_change("m1", model="b", effort="high")
    ref = store.get("m1")
    assert ref.model == "b" and ref.effort == "high"
    store.append_model_change("m1", model="c")
    assert store.get("m1").model == "c"
    assert store.get("m1").effort == "high"
    with pytest.raises(ValueError, match="不存在"):
        store.append_model_change("ghost", model="x")


def test_memory_store_meta_and_title():
    """MemoryStore 与文件后端同语义:meta 后写覆盖 + 标题派生。"""
    store = MemoryStore()
    store.create("m1")
    store.append_message("m1", Message(role="user", content="一条非常长的用户消息用来测试标题的截断行为"))
    assert store.get("m1").title.endswith("…")
    store.set_meta("m1", "name", "命名会话")
    assert store.get("m1").title == "命名会话"
    assert store.get_meta("m1", "name") == "命名会话"
    with pytest.raises(ValueError, match="不存在"):
        store.set_meta("ghost", "name", "x")
