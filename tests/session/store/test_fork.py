"""fork behavior tests."""

from tests.session.store.fixtures import *  # noqa: F401,F403


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

