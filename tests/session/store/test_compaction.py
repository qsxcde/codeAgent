"""compaction behavior tests."""

from tests.session.store.fixtures import *  # noqa: F401,F403


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

