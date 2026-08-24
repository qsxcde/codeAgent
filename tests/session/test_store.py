"""会话存储测试:JSONL 追加不重写、父级链回放、版本解析、并发写串行化、内存后端。"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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


def test_corrupt_line_skipped_not_fatal(tmp_path):
    """残缺行容错:崩溃残留的坏行跳过,前后条目照常解析(回归:M-4)。

    原实现任何 JSONDecodeError 直接 raise——append-only 崩溃易留无换行残缺
    行,单个坏文件让整个会话列表(continue_recent / /sessions list)不可达。
    """
    store = _store(tmp_path)
    store.create("s1")
    path = tmp_path / "sessions" / "s1.jsonl"
    path.write_text(
        '{"type": "session", "version": 1}\n'
        '{"type": "message", "id": "m1", "parentId": null, "role": "user", "content": "好"}\n'
        "not-json\n"  # 残缺行(模拟崩溃残留)
        '{"type": "message", "id": "m2", "parentId": null, "role": "user", "content": "完整"}\n',
        encoding="utf-8",
    )
    assert [m.id for m in store.load_messages("s1")] == ["m1", "m2"]  # 坏行跳过,前后都保留
    assert store.get("s1") is not None  # 扫描路径同样容错


def test_jsonl_reads_do_not_materialize_file_with_read_text(tmp_path, monkeypatch):
    """文件读取路径使用流式句柄,不依赖整文件 ``Path.read_text``。"""
    store = _store(tmp_path)
    store.create("s1")
    message = Message(role="user", content="stream me")
    store.append_message("s1", message)
    store.append_usage("s1", {"input_tokens": 3})

    original_read_text = Path.read_text

    def fail_for_jsonl(self, *args, **kwargs):
        if self.suffix == ".jsonl":
            raise AssertionError("session JSONL must be read line by line")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_for_jsonl)

    assert store.get("s1").title == "stream me"
    assert [m.id for m in store.load_messages("s1")] == [message.id]
    assert store.load_context("s1").messages[0].id == message.id
    assert store.load_usage("s1").input_tokens == 3


def test_session_index_is_created_and_rebuilt_when_corrupt(tmp_path):
    """会话索引是可重建缓存,损坏时不影响 JSONL 读取。"""
    store = _store(tmp_path)
    store.create("s1")
    message = Message(role="user", content="indexed session")
    store.append_message("s1", message)
    store.append_usage("s1", {"input_tokens": 7, "output_tokens": 2})

    index_path = tmp_path / "sessions" / "s1.index.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["usage"]["input_tokens"] == 7
    assert index["session"]["title"] == "indexed session"

    index_path.write_text("not-json\n", encoding="utf-8")
    assert store.get("s1").title == "indexed session"
    assert store.load_usage("s1").output_tokens == 2
    rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
    assert rebuilt["usage"]["input_tokens"] == 7


def test_semantically_incomplete_index_is_rebuilt(tmp_path):
    """索引字段不完整时不能命中缓存,必须从 JSONL 重建。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="rebuild me"))
    index_path = tmp_path / "sessions" / "s1.index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    del index["session"]["title"]
    index_path.write_text(json.dumps(index) + "\n", encoding="utf-8")

    assert store.get("s1").title == "rebuild me"
    assert json.loads(index_path.read_text(encoding="utf-8"))["session"]["title"] == "rebuild me"


def test_stale_index_rebuilds_after_external_jsonl_append(tmp_path):
    """源 JSONL 外部追加后,指纹失效会触发索引重建。"""
    store = _store(tmp_path)
    store.create("s1")
    path = tmp_path / "sessions" / "s1.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "usage", "input": 9}) + "\n")

    assert store.load_usage("s1").input_tokens == 9
    index = json.loads(
        (tmp_path / "sessions" / "s1.index.json").read_text(encoding="utf-8")
    )
    assert index["usage"]["input_tokens"] == 9


def test_index_write_failure_does_not_block_jsonl_append(tmp_path, monkeypatch):
    """索引写入失败时 JSONL 追加仍成功,后续读取可直接扫描。"""
    store = _store(tmp_path)
    store.create("s1")

    def fail_index_write(*args, **kwargs):
        raise OSError("index unavailable")

    monkeypatch.setattr(store, "_write_index", fail_index_write)
    message = Message(role="user", content="append despite cache failure")
    store.append_message("s1", message)

    assert store.load_messages("s1")[0].id == message.id
    assert store.get("s1").title == "append despite cache…"


def test_create_is_fail_open_when_index_fingerprint_fails(tmp_path, monkeypatch):
    """创建时索引初始化失败不撤销已经写入的 JSONL header。"""
    store = _store(tmp_path)

    def fail_fingerprint(*args, **kwargs):
        raise OSError("stat unavailable")

    monkeypatch.setattr(store, "_source_fingerprint", fail_fingerprint)
    ref = store.create("s1")

    assert ref.id == "s1"
    assert (tmp_path / "sessions" / "s1.jsonl").exists()


def test_create_index_cannot_overwrite_concurrent_append(tmp_path, monkeypatch):
    """创建初始索引期间持有会话锁,不会覆盖并发追加后的摘要。"""
    store = _store(tmp_path)
    original_write_index = store._write_index
    original_read_index = store._read_valid_index
    initial_write_entered = threading.Event()
    release_initial_write = threading.Event()
    append_acquired_lock = threading.Event()
    write_count = 0

    def controlled_write_index(*args, **kwargs):
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            initial_write_entered.set()
            assert release_initial_write.wait(2)
        return original_write_index(*args, **kwargs)

    def observe_append_lock(path):
        append_acquired_lock.set()
        return original_read_index(path)

    monkeypatch.setattr(store, "_write_index", controlled_write_index)
    monkeypatch.setattr(store, "_read_valid_index", observe_append_lock)
    create_errors: list[BaseException] = []

    def create_session():
        try:
            store.create("s1")
        except BaseException as exc:  # pragma: no cover - 仅用于线程错误传递
            create_errors.append(exc)

    create_thread = threading.Thread(target=create_session)
    create_thread.start()
    assert initial_write_entered.wait(2)

    message = Message(role="user", content="concurrent append")
    append_thread = threading.Thread(
        target=lambda: store.append_message("s1", message)
    )
    append_thread.start()
    append_acquired_lock.wait(0.2)
    release_initial_write.set()
    create_thread.join(2)
    append_thread.join(2)

    assert not create_errors
    assert store.get("s1").title == "concurrent append"


def test_corrupt_session_does_not_block_listing(tmp_path):
    """单个损坏会话被隔离,不阻断其余枚举(回归:M-4)。"""
    store = _store(tmp_path)
    store.create("good")
    bad = tmp_path / "sessions" / "bad.jsonl"
    bad.write_text("not-json\n", encoding="utf-8")  # header 残缺 → 结构性损坏
    assert [r.id for r in store.list()] == ["good"]
    with pytest.raises(ValueError, match="header"):
        store.get("bad")  # 按直接 id 访问给出明确错误而非「不存在」


def test_session_files_private_perms(tmp_path):
    """会话文件 0600 / sessions 目录 0700(回归:M-10)。

    转录含工具输出/文件内容/可能密钥,默认 umask 022 下 0644 世界可读;
    Windows 无 POSIX 权限位语义,条件断言。
    """
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="hi"))
    if os.name != "nt":
        assert (tmp_path / "sessions").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "sessions" / "s1.jsonl").stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "sessions" / "s1.index.json").stat().st_mode & 0o777 == 0o600


def test_valid_index_serves_metadata_without_scanning_jsonl(tmp_path, monkeypatch):
    """有效索引命中时列表元数据和用量不重复扫描 JSONL。"""
    store = _store(tmp_path)
    store.create("s1", model="model-a")
    store.append_message("s1", Message(role="user", content="cached"))
    store.append_usage("s1", {"input_tokens": 4})

    def fail_scan(*args, **kwargs):
        raise AssertionError("valid index should avoid JSONL scan")

    monkeypatch.setattr(store, "_iter_entries", fail_scan)
    assert store.get("s1").model == "model-a"
    assert store.list()[0].title == "cached"
    assert store.load_usage("s1").input_tokens == 4


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


# -- session-fork change:会话分叉 --------------------------------------------


def _fill_session(store, session_id: str) -> list[Message]:
    """写入 user → assistant → user → assistant 消息链,返回消息列表。"""
    store.create(session_id, model="deepseek-v4-flash", effort="high")
    m1 = Message(role="user", content="第一问")
    m2 = Message(role="assistant", content="第一答", parent_id=m1.id)
    m3 = Message(role="user", content="第二问", parent_id=m2.id)
    m4 = Message(role="assistant", content="第二答", parent_id=m3.id)
    for m in (m1, m2, m3, m4):
        store.append_message(session_id, m)
    return [m1, m2, m3, m4]


def test_fork_copies_history_before_target(tmp_path):
    """分叉:新会话 = 分叉点之前(不含该 user 消息)消息副本,parentSession 记 header。"""
    store = JsonFileStore(tmp_path)
    msgs = _fill_session(store, "s1")
    ref = store.fork("s1", msgs[2].id, "s2")  # 从「第二问」之前分叉

    assert ref.parent_session == "s1"
    assert ref.model == "deepseek-v4-flash" and ref.effort == "high"  # header 元数据复制
    forked = store.load_messages("s2")
    assert [m.id for m in forked] == [msgs[0].id, msgs[1].id]  # 第一问/第一答,不含第二问
    assert forked[1].parent_id == msgs[0].id  # parentId 链保持


def test_fork_streams_with_bounded_entry_lifetime(tmp_path, monkeypatch):
    """文件分叉不会同时持有完整源历史的 entry 对象。"""
    store = JsonFileStore(tmp_path)
    store.create("s1")
    source_path = tmp_path / "s1.jsonl"

    class GuardedEntry(dict):
        active = 0
        peak = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            type(self).active += 1
            type(self).peak = max(type(self).peak, type(self).active)

        def __del__(self):
            type(self).active -= 1

    target_id = "m249"

    def guarded_entries():
        yield GuardedEntry(
            {
                "type": "session",
                "version": CURRENT_VERSION,
                "id": "s1",
                "timestamp": "t",
                "cwd": "/w",
            }
        )
        for i in range(250):
            yield GuardedEntry(
                {
                    "type": "message",
                    "id": f"m{i}",
                    "parentId": None,
                    "role": "user" if i == 249 else "assistant",
                    "content": f"message-{i}",
                }
            )

    original_iter_entries = store._iter_entries

    def guarded_iter_entries(path):
        if path == source_path:
            return guarded_entries()
        return original_iter_entries(path)

    monkeypatch.setattr(store, "_iter_entries", guarded_iter_entries)
    store.fork("s1", target_id, "s2")

    assert GuardedEntry.peak < 20


def test_fork_keeps_original_file_untouched(tmp_path):
    """原会话文件零修改(append-only 承诺不破)。"""
    store = JsonFileStore(tmp_path)
    msgs = _fill_session(store, "s1")
    before = len((tmp_path / "s1.jsonl").read_text(encoding="utf-8").splitlines())
    store.fork("s1", msgs[0].id, "s2")
    after = len((tmp_path / "s1.jsonl").read_text(encoding="utf-8").splitlines())
    assert before == after
    assert store.load_messages("s1")  # 原历史完整


def test_fork_validation_errors(tmp_path):
    """分叉点校验:非 user 消息 / 不存在 / 目标已存在 → 明确错误,不产生会话。"""
    store = JsonFileStore(tmp_path)
    msgs = _fill_session(store, "s1")
    with pytest.raises(ValueError, match="必须是 user 消息"):
        store.fork("s1", msgs[1].id, "s2")  # assistant 消息
    with pytest.raises(ValueError, match="消息不存在"):
        store.fork("s1", "ghost-id", "s2")
    with pytest.raises(ValueError, match="会话不存在"):
        store.fork("ghost", msgs[0].id, "s2")
    store.fork("s1", msgs[0].id, "s2")
    with pytest.raises(ValueError, match="会话已存在"):
        store.fork("s1", msgs[2].id, "s2")
    assert (tmp_path / "s2.jsonl").exists()
    assert len(store.list()) == 2


def test_fork_first_message_yields_empty_history(tmp_path):
    """分叉点是首条 user 消息:新会话仅 header(空历史,对齐 Pi 无 parent 分支)。"""
    store = JsonFileStore(tmp_path)
    msgs = _fill_session(store, "s1")
    ref = store.fork("s1", msgs[0].id, "s2")
    assert ref.parent_session == "s1"
    assert store.load_messages("s2") == []


def test_memory_store_fork_semantics():
    """MemoryStore 与文件后端同语义:切片复制 + parentSession + 校验。"""
    store = MemoryStore()
    msgs = _fill_session(store, "m1")
    ref = store.fork("m1", msgs[2].id, "m2")
    assert ref.parent_session == "m1"
    assert [m.id for m in store.load_messages("m2")] == [msgs[0].id, msgs[1].id]
    assert store.load_messages("m1")  # 原会话完整
    with pytest.raises(ValueError, match="必须是 user 消息"):
        store.fork("m1", msgs[1].id, "m3")
    with pytest.raises(ValueError, match="消息不存在"):
        store.fork("m1", "ghost", "m3")


# -- session-compaction change:压缩 entry 语义与上下文重构 ---------------------


def test_compaction_entry_id_parent_and_first_kept(tmp_path):
    """压缩 entry:id 自动分配、parentId/firstKeptEntryId 落盘、返回 entry id。"""
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(3)]
    for m in msgs:
        store.append_message("s1", m)
    entry_id = store.append_compaction(
        "s1",
        CompactionEntry(
            summary="摘要",
            parent_id=msgs[-1].id,
            first_kept_entry_id=msgs[1].id,
        ),
    )
    assert entry_id  # uuid7
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["id"] == entry_id
    assert record["parentId"] == msgs[-1].id
    assert record["firstKeptEntryId"] == msgs[1].id


def test_load_context_without_compaction_returns_all(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(3)]
    for m in msgs:
        store.append_message("s1", m)
    state = store.load_context("s1")
    assert state.summary is None and state.entry_id is None
    assert [m.id for m in state.messages] == [m.id for m in msgs]


def test_load_context_reconstructs_summary_plus_kept(tmp_path):
    """压缩后上下文 = 最新摘要 + firstKeptEntryId 起消息(uuid7 时间序过滤)。"""
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(5)]
    for m in msgs:
        store.append_message("s1", m)
    store.append_compaction(
        "s1",
        CompactionEntry(summary="摘要1", first_kept_entry_id=msgs[2].id),
    )
    state = store.load_context("s1")
    assert state.summary == "摘要1"
    assert [m.id for m in state.messages] == [msgs[2].id, msgs[3].id, msgs[4].id]
    # 全量回放仍包含被压缩窗口(物理保留)
    assert len(store.load_messages("s1")) == 5


def test_load_context_latest_compaction_wins(tmp_path):
    """二次压缩后只认最新边界;新消息(压缩后追加)包含在上下文中。"""
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(6)]
    for m in msgs:
        store.append_message("s1", m)
    store.append_compaction("s1", CompactionEntry(summary="摘要1", first_kept_entry_id=msgs[2].id))
    store.append_compaction("s1", CompactionEntry(summary="摘要2", first_kept_entry_id=msgs[4].id))
    state = store.load_context("s1")
    assert state.summary == "摘要2"
    assert [m.id for m in state.messages] == [msgs[4].id, msgs[5].id]


def test_memory_store_load_context_semantics():
    """MemoryStore 与文件后端同语义:摘要 + 保留消息 + 最新边界。"""
    store = MemoryStore()
    store.create("m1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(4)]
    for m in msgs:
        store.append_message("m1", m)
    store.append_compaction("m1", CompactionEntry(summary="摘要", first_kept_entry_id=msgs[1].id))
    state = store.load_context("m1")
    assert state.summary == "摘要"
    assert [m.id for m in state.messages] == [msgs[1].id, msgs[2].id, msgs[3].id]
    with pytest.raises(ValueError, match="会话不存在"):
        store.load_context("ghost")


def test_fork_carries_compaction_summary(tmp_path):
    """fork 已压缩会话:新会话携带摘要 + 切点起消息(回归:此前摘要丢失)。"""
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(5)]
    for m in msgs:
        store.append_message("s1", m)
    store.append_compaction("s1", CompactionEntry(summary="摘要1", first_kept_entry_id=msgs[2].id))
    # 从 m4 分叉(在保留窗口内):复制 m2..m3 + 摘要
    store.fork("s1", msgs[4].id, "s2")
    state = store.load_context("s2")
    assert state.summary == "摘要1"
    assert [m.id for m in state.messages] == [msgs[2].id, msgs[3].id]
    # 父会话不受影响
    assert len(store.load_messages("s1")) == 5


def test_fork_before_compaction_boundary_keeps_summary_only(tmp_path):
    """分叉点在切点之前:窗口消息已被摘要,新会话只有摘要(不复制物理窗口)。"""
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(5)]
    for m in msgs:
        store.append_message("s1", m)
    store.append_compaction("s1", CompactionEntry(summary="摘要1", first_kept_entry_id=msgs[3].id))
    store.fork("s1", msgs[1].id, "s2")  # 分叉点在 firstKept 之前
    state = store.load_context("s2")
    assert state.summary == "摘要1"
    assert state.messages == []  # 全部窗口内容由摘要承载


def test_memory_store_fork_carries_compaction():
    """MemoryStore 与文件后端同语义:fork 携带摘要。"""
    store = MemoryStore()
    store.create("m1")
    msgs = [Message(role="user", content=f"m{i}") for i in range(4)]
    for m in msgs:
        store.append_message("m1", m)
    store.append_compaction("m1", CompactionEntry(summary="摘要", first_kept_entry_id=msgs[2].id))
    store.fork("m1", msgs[3].id, "m2")
    state = store.load_context("m2")
    assert state.summary == "摘要"
    assert [m.id for m in state.messages] == [msgs[2].id]


# -- usage 落库(cost-transparency)---------------------------------------------


def _usage_dict(input_tokens=0, output_tokens=0, reasoning_tokens=0, cached_tokens=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
    }


def test_json_store_usage_append_and_aggregate(tmp_path):
    """文件后端:usage entry 追加 + 读侧累计聚合(逐次相加)。"""
    store = _store(tmp_path)
    store.create("s1")
    store.append_usage("s1", _usage_dict(input_tokens=100, output_tokens=20, cached_tokens=60))
    store.append_usage("s1", _usage_dict(input_tokens=50, output_tokens=10, reasoning_tokens=5, cached_tokens=0))
    total = store.load_usage("s1")
    assert total.input_tokens == 150
    assert total.output_tokens == 30
    assert total.reasoning_tokens == 5
    assert total.cached_tokens == 60
    # append-only:usage entry 逐条追加,历史不被重写
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    usage_entries = [l for l in lines if json.loads(l).get("type") == "usage"]
    assert len(usage_entries) == 2


def test_json_store_usage_empty_and_legacy_compat(tmp_path):
    """空会话返回全零;旧文件(无 usage entry)向后兼容不报错。"""
    store = _store(tmp_path)
    store.create("s1")
    # 仅消息、无 usage:兼容旧文件
    store.append_message("s1", Message(role="user", content="hi"))
    total = store.load_usage("s1")
    assert total.input_tokens == 0
    assert total.output_tokens == 0
    assert total.cached_tokens == 0
    with pytest.raises(ValueError, match="不存在"):
        store.load_usage("nope")


def test_json_store_usage_missing_fields_tolerated(tmp_path):
    """usage entry 字段缺失容错:缺省 0,不阻断聚合。"""
    store = _store(tmp_path)
    store.create("s1")
    # 直接写残缺 usage entry(无 reasoning/cached)
    store.append_usage("s1", {"input_tokens": 10})
    total = store.load_usage("s1")
    assert total.input_tokens == 10
    assert total.reasoning_tokens == 0
    assert total.cached_tokens == 0


def test_memory_store_usage_aggregate_consistent():
    """内存后端与文件后端同语义:累计聚合 + 空会话空态。"""
    store = MemoryStore()
    store.create("m1")
    store.append_usage("m1", _usage_dict(input_tokens=100, output_tokens=20, cached_tokens=60))
    store.append_usage("m1", _usage_dict(input_tokens=50, output_tokens=10, cached_tokens=0))
    total = store.load_usage("m1")
    assert total.input_tokens == 150
    assert total.output_tokens == 30
    assert total.cached_tokens == 60
    with pytest.raises(ValueError, match="不存在"):
        store.load_usage("nope")
    # 无 usage 记录的会话:全零
    store.create("m2")
    assert store.load_usage("m2").input_tokens == 0
