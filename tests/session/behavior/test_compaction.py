"""compaction behavior tests."""

import asyncio

from tests.session.behavior.fixtures import *  # noqa: F401,F403


async def test_compact_summarizes_and_truncates_history():
    """手动压缩:摘要窗口 → 截断历史 → entry 落盘(store 与内存一致)。"""
    store = MemoryStore()
    model = FakeClient(responses=["答1", "答2", "答3"])
    sess = _compact_session(model, store=store, summarizer=_StubSummarizer())
    for text in (_long("问1"), _long("问2"), _long("问3")):
        await (sess.run(text))
    assert len(sess.history) >= 6  # 3 user + 3 assistant
    before_full = len(store.load_messages(sess.session_id))
    history_before_compact = len(sess.history)

    async def scenario() -> None:
        return await sess.compact()

    assert await (scenario()) is True
    assert sess._summary is not None and sess._summary.startswith("SUM[")
    # 真截断:历史收缩而非仅非空(此前仅 assert truthy,压缩空转也通过,审计 M-9 同批)
    assert 0 < len(sess.history) < history_before_compact
    assert len(store.load_messages(sess.session_id)) == before_full  # 物理保留
    state = store.load_context(sess.session_id)
    assert state.summary == sess._summary
    assert state.entry_id == sess._summary_entry_id
    assert [m.id for m in state.messages] == [m.id for m in sess.history]



async def test_compact_noop_when_all_kept():
    """短历史全部保留:压缩返回 False,无 entry 落盘。"""
    store = MemoryStore()
    sess = _compact_session(FakeClient(response="答"), store=store, summarizer=_StubSummarizer())
    await (sess.run("问"))
    assert await (sess.compact()) is False
    assert sess._summary is None



async def test_compact_without_summarizer_raises():
    """未注入 Summarizer → 明确报错(压缩不可用)。"""
    sess = _compact_session(FakeClient(response="答"))
    with pytest.raises(ValueError, match="压缩不可用"):
        await (sess.compact())



async def test_compact_failure_emits_terminal_finished_event():
    sess = _compact_session(
        FakeClient(response="答"), summarizer=_FailingSummarizer(), compact_budget=50
    )
    for text in (_long("问1"), _long("问2"), _long("问3")):
        await (sess.run(text))
    seen: list = []
    sess.subscribe(seen.append)

    with pytest.raises(RuntimeError, match="摘要服务失败"):
        await (sess.compact())

    finished = [event for event in seen if event.type == EventType.COMPACTION_FINISHED]
    assert finished and finished[-1].metadata["success"] is False
    assert finished[-1].metadata["error_code"] == "compaction_failed"



async def test_after_compact_run_injects_summary_and_links_parent():
    """压缩后继续对话:摘要注入模型输入;新 user 消息父级接回压缩记录;
    虚拟摘要消息不落盘。"""
    store = MemoryStore()
    model = FakeClient(responses=["答1", "答2", "答3", "答4"])
    sess = _compact_session(model, store=store, summarizer=_StubSummarizer())
    for text in (_long("问1"), _long("问2"), _long("问3")):
        await (sess.run(text))
    assert await (sess.compact()) is True
    entry_id = sess._summary_entry_id
    # 保留消息的内部链不被改写(物理历史完整)
    kept_user = next(m for m in sess.history if m.role == "user")
    assert kept_user.parent_id != entry_id
    model.call_history.clear()
    await (sess.run(_long("问4")))
    # 压缩后首条新 user 消息父级接回压缩记录
    new_user = next(m for m in sess.history if m.role == "user" and m is not kept_user)
    assert new_user.parent_id == entry_id
    # 摘要注入模型输入(首条消息)
    assert model.call_history
    first = model.call_history[-1]["messages"][0]
    assert first["role"] == "user" and "以下为会话历史摘要" in first["content"]
    # 虚拟摘要消息不落盘;新消息追加
    stored = store.load_messages(sess.session_id)
    assert not any(m.id.startswith("summary-") for m in stored)
    assert any(m.content.startswith("问4") for m in stored)



async def test_threshold_auto_compact_triggers():
    """阈值触发:下一次请求预算达到比例阈值 → turn_end 后自动压缩。"""
    store = MemoryStore()
    model = FakeClient(
        responses=["答1", "答2", "答3", "答4", "答5", "答6"],
    )
    sess = _compact_session(
        model,
        store=store,
        summarizer=_StubSummarizer(),
        context_window=2_000,
        compact_budget=600,
        compaction_policy=CompactionPolicyConfig(
            trigger_ratio=0.8,
            target_ratio=0.6,
            trigger_headroom_tokens=0,
        ),
        with_tools=False,
    )
    for text in tuple(_long(f"问{i}" * 600) for i in range(1, 7)):
        await (sess.run(text))
    assert sess._summary is not None  # 自动压缩已发生
    assert store.load_context(sess.session_id).summary == sess._summary


async def test_auto_compaction_emits_budget_diagnostics_without_provider_usage():
    seen: list = []
    model = FakeClient(responses=["答1", "答2", "答3", "答4", "答5", "答6"])
    sess = _compact_session(
        model,
        store=MemoryStore(),
        summarizer=_StubSummarizer(),
        context_window=2_000,
        compact_budget=600,
        compaction_policy=CompactionPolicyConfig(
            trigger_ratio=0.8,
            target_ratio=0.6,
            trigger_headroom_tokens=0,
        ),
        with_tools=False,
    )
    sess.subscribe(seen.append)

    for text in tuple(_long(f"问{i}" * 600) for i in range(1, 7)):
        await sess.run(text)

    finished = [event for event in seen if event.type == EventType.COMPACTION_FINISHED]
    assert finished
    assert any(
        event.metadata.get("trigger") == "auto"
        and event.metadata.get("status") == "compacted"
        and event.metadata.get("before_input_tokens") is not None
        for event in finished
    )



async def test_second_compact_incremental_merge():
    """二次压缩:桩摘要收到既有摘要(增量合并);摘要链 compaction1 → compaction2。"""
    store = MemoryStore()
    model = FakeClient(responses=[f"答{i}" for i in range(8)])
    summarizer = _StubSummarizer()
    sess = _compact_session(model, store=store, summarizer=summarizer)
    for text in (_long("问1"), _long("问2"), _long("问3"), _long("问4")):
        await (sess.run(text))
    assert await (sess.compact()) is True
    first_entry = sess._summary_entry_id
    first_summary = sess._summary
    for text in (_long("问5"), _long("问6"), _long("问7"), _long("问8")):
        await (sess.run(text))
    assert await (sess.compact()) is True
    # 二次压缩:既有摘要传入(增量合并,桩拼接 <prev>)
    assert summarizer.calls[-1][1] == first_summary
    assert first_summary in sess._summary
    # 摘要链:new entry 的 parentId = 旧 entry id
    _, second = store._compactions[-1]
    assert second.parent_id == first_entry
    state = store.load_context(sess.session_id)
    assert state.entry_id != first_entry  # 新 entry
    assert state.summary == sess._summary


async def test_concurrent_compaction_requests_append_only_one_entry():
    store = MemoryStore()
    sess = _compact_session(
        FakeClient(response="答"),
        store=store,
        summarizer=_StubSummarizer(),
    )
    for text in (_long("问1"), _long("问2"), _long("问3"), _long("问4")):
        await sess.run(text)

    results = await asyncio.gather(sess.compact(), sess.compact())

    assert sorted(results) == [False, True]
    assert len(store._compactions) == 1
