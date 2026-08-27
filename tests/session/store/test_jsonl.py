"""jsonl behavior tests."""

from tests.session.store.fixtures import *  # noqa: F401,F403


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


def test_legacy_file_without_activity_uses_creation_timestamp(tmp_path):
    """旧 JSONL 无活动字段时,最近活动回退为创建时间。"""
    store = _store(tmp_path)
    path = tmp_path / "sessions" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "session",
                "version": 1,
                "id": "s1",
                "timestamp": "2026-08-27T00:00:00.000",
                "cwd": "/w",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    ref = store.get("s1")
    assert ref.last_activity_at == ref.timestamp


def test_message_activity_timestamp_survives_reopen(tmp_path, monkeypatch):
    """消息活动时间写入 JSONL 并可在索引失效后重建。"""
    from codeagent.session.persistence import jsonl_store

    clock = iter(
        (
            "2026-08-27T00:00:00.000",
            "2026-08-27T00:00:01.000",
        )
    )
    monkeypatch.setattr(jsonl_store, "_now", lambda: next(clock))
    store = _store(tmp_path)
    store.create("s1")
    store.append_message("s1", Message(role="user", content="hello"))

    path = tmp_path / "sessions" / "s1.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["lastActivityAt"] == "2026-08-27T00:00:00.000"
    assert records[1]["timestamp"] == "2026-08-27T00:00:01.000"

    (tmp_path / "sessions" / "s1.index.json").unlink()
    reopened = JsonFileStore(tmp_path / "sessions")
    assert reopened.get("s1").last_activity_at == "2026-08-27T00:00:01.000"



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

