"""memory behavior tests."""

from tests.session.store.fixtures import *  # noqa: F401,F403


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

