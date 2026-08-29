"""会话管理器测试(design D1):生命周期、订阅跟随、单活语义、继续最近。"""

from __future__ import annotations

import asyncio

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import AgentLoopConfig, EventType
from codeagent.session import SessionManager
from codeagent.session.compaction import CompactionPolicyConfig
from codeagent.session.persistence import (
    CompactionEntry,
    JsonFileStore,
    MemoryStore,
    SessionQuery,
    SessionRecoveryError,
)
from codeagent.session.runtime.state import RunPhase


def _manager(client: FakeClient | None = None, store=None, **kwargs) -> SessionManager:
    config = AgentLoopConfig(model=ChatModelPort(client or FakeClient(response="OK")), tools=[])
    return SessionManager(config, store=store, **kwargs)


def _event_types(seen) -> list[str]:
    return [e.type for e in seen]


def test_create_keeps_empty_session_in_memory_only():
    """打开新会话但未对话时,不应在 store 中创建空记录。"""
    store = MemoryStore()
    mgr = _manager(store=store, model="deepseek-v4-flash", effort="high")
    a = mgr.create()
    assert mgr.current is a
    assert store.list() == []
    assert store.get(a.session_id) is None


def test_manager_rename_persists_normalized_title_without_changing_messages():
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()

    async def scenario() -> None:
        await session.run("原始问题")

    asyncio.run(scenario())
    before_messages = store.load_messages(session.session_id)
    before_activity = store.get(session.session_id).last_activity_at

    title = mgr.rename(session.session_id, "  新标题\n用于回归测试  ")

    assert title == "新标题 用于回归测试"
    assert store.get(session.session_id).title == title
    assert store.load_messages(session.session_id) == before_messages
    assert store.get(session.session_id).last_activity_at == before_activity


def test_manager_rename_rejects_blank_and_missing_storage():
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    with pytest.raises(ValueError, match="标题不能为空"):
        mgr.rename(session.session_id, " \n\t ")

    without_store = _manager()
    empty = without_store.create()
    with pytest.raises(ValueError, match="持久化"):
        without_store.rename(empty.session_id, "标题")


def test_manager_rename_persists_deferred_empty_session():
    """延迟落盘的当前空会话也可以先命名,之后仍从同一会话继续对话。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()

    assert mgr.rename(session.session_id, "预先命名") == "预先命名"
    assert store.get(session.session_id).title == "预先命名"
    assert store.load_messages(session.session_id) == []


async def test_manager_rename_preserves_compaction_and_fork_relationship():
    """重命名不改压缩状态,且后续分叉仍以原会话为 parent。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    root = mgr.create()
    await root.run("根会话")
    messages = store.load_messages(root.session_id)
    store.append_compaction(
        root.session_id,
        CompactionEntry(summary="根摘要", first_kept_entry_id=messages[0].id),
    )
    before_context = store.load_context(root.session_id)

    mgr.rename(root.session_id, "重构根会话")
    child = mgr.fork(root.session_id, messages[0].id)

    assert store.load_context(root.session_id) == before_context
    assert store.get(root.session_id).title == "重构根会话"
    assert store.get(child.session_id).parent_session == root.session_id


async def test_manager_query_overlays_runtime_status_and_restart_idle():
    """管理器为驻留会话提供运行态,新管理器不伪造旧运行终态。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    await session.run("完成一轮")

    assert session.is_running is False
    assert [ref.id for ref in mgr.list(SessionQuery(status="completed"))] == [session.session_id]

    session._runtime.start_run()
    assert session.is_running is True
    assert [ref.id for ref in mgr.list(SessionQuery(status="running"))] == [session.session_id]
    session._runtime.finish_run(RunPhase.CANCELLED)
    assert [ref.id for ref in mgr.list(SessionQuery(status="cancelled"))] == [session.session_id]
    session._runtime.start_run()
    session._runtime.finish_run(RunPhase.FAILED)
    assert [ref.id for ref in mgr.list(SessionQuery(status="failed"))] == [session.session_id]

    restarted = _manager(store=store)
    idle_refs = restarted.list(SessionQuery(status="idle"))
    assert [ref.id for ref in idle_refs] == [session.session_id]


async def test_manager_query_is_read_only_for_session_state():
    """查询不会切换当前会话或触碰消息、活动时间和压缩上下文。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    await session.run("保持不变")
    before_ref = store.get(session.session_id)
    before_messages = store.load_messages(session.session_id)
    before_context = store.load_context(session.session_id)

    refs = mgr.list(SessionQuery(text="保持"))

    assert [ref.id for ref in refs] == [session.session_id]
    assert mgr.current is session
    assert store.get(session.session_id) == before_ref
    assert store.load_messages(session.session_id) == before_messages
    assert store.load_context(session.session_id) == before_context


async def test_manager_archive_unarchive_preserves_history_and_visibility():
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    await session.run("归档但不删除")
    before_messages = store.load_messages(session.session_id)
    before_context = store.load_context(session.session_id)

    assert mgr.archive_many([session.session_id]) == {session.session_id: "archived"}
    assert mgr.list() == []
    assert [ref.id for ref in mgr.list(SessionQuery(archived=True))] == [session.session_id]
    assert store.load_messages(session.session_id) == before_messages
    assert store.load_context(session.session_id) == before_context

    assert mgr.unarchive_many([session.session_id]) == {session.session_id: "unarchived"}
    assert [ref.id for ref in mgr.list()] == [session.session_id]


async def test_manager_delete_many_preflights_and_protects_current_session():
    store = MemoryStore()
    mgr = _manager(store=store)
    first = mgr.create()
    await first.run("第一个")
    second = mgr.create()
    await second.run("第二个")

    with pytest.raises(ValueError, match="确认"):
        mgr.delete_many([first.session_id], confirmed=False)
    with pytest.raises(ValueError, match="预检|不存在"):
        mgr.delete_many([first.session_id, "missing"], confirmed=True)
    assert store.get(first.session_id) is not None

    assert mgr.delete_many([first.session_id], confirmed=True) == {first.session_id: "deleted"}
    assert store.get(first.session_id) is None
    assert mgr.current is second
    with pytest.raises(ValueError, match="当前会话"):
        mgr.delete_many([second.session_id], confirmed=True)


async def test_manager_delete_many_reports_partial_failure_and_running_protection():
    class FailingStore(MemoryStore):
        fail_id = ""

        def delete(self, session_id: str) -> None:
            if session_id == self.fail_id:
                raise OSError("磁盘不可用")
            super().delete(session_id)

    store = FailingStore()
    mgr = _manager(store=store)
    first = mgr.create()
    await first.run("可删除")
    failing = mgr.create()
    await failing.run("存储失败")
    store.fail_id = failing.session_id
    current = mgr.create()
    await current.run("当前")

    results = mgr.delete_many([first.session_id, failing.session_id], confirmed=True)
    assert results[first.session_id] == "deleted"
    assert results[failing.session_id].startswith("failed:")
    assert store.get(failing.session_id) is not None

    running = mgr.create()
    await running.run("运行中")
    mgr.create()
    running._runtime.start_run()
    with pytest.raises(ValueError, match="运行中"):
        mgr.delete_many([running.session_id], confirmed=True)
    running._runtime.finish_run(RunPhase.CANCELLED)


def test_manager_exposes_recovery_report_for_existing_and_missing_sessions(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    mgr = _manager(store=store)

    assert mgr.recovery_report("s1").status == "healthy"
    assert mgr.recovery_report("missing").diagnostics[0].code == "missing_session"


def test_manager_switch_rejects_incompatible_session_without_replacing_current(tmp_path):
    store = JsonFileStore(tmp_path / "sessions")
    store.create("bad")
    path = tmp_path / "sessions" / "bad.jsonl"
    path.write_text('{"type":"session","version":999,"id":"bad"}\n', encoding="utf-8")
    mgr = _manager(store=store)
    current = mgr.create()

    with pytest.raises(SessionRecoveryError) as caught:
        mgr.switch("bad")

    assert caught.value.report.diagnostics[0].code == "incompatible_version"
    assert mgr.current is current


def test_manager_passes_compaction_policy_to_adopted_session():
    policy = CompactionPolicyConfig(
        trigger_ratio=0.75,
        target_ratio=0.5,
        trigger_headroom_tokens=100,
        min_recent_turns=2,
    )

    session = _manager(compaction_policy=policy).create()

    assert session._compaction_policy == policy


async def test_create_persists_header_after_successful_first_turn():
    """首轮成功产生消息后,才创建带模型配置的持久化 header。"""
    store = MemoryStore()
    mgr = _manager(store=store, model="deepseek-v4-flash", effort="high")
    a = mgr.create()
    await (a.run("你好"))

    assert len(store.list()) == 1
    ref = store.get(a.session_id)
    assert ref.model == "deepseek-v4-flash" and ref.effort == "high"


async def test_failed_first_turn_does_not_persist_empty_session():
    """首轮失败回滚后,空会话仍不应出现在 store。"""

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("首轮失败")

    store = MemoryStore()
    mgr = _manager(BoomModel(response="不会返回"), store=store)
    session = mgr.create()
    await (session.run("失败的首轮"))

    assert session.history == []
    assert store.list() == []
    assert store.get(session.session_id) is None


async def test_switch_restores_history():
    """switch:恢复既有会话历史,新消息追加到同一会话。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    await (a.run("第一轮"))
    b = mgr.create()
    assert mgr.current is b
    a2 = mgr.switch(a.session_id)
    assert [m.role for m in a2.history] == ["user", "assistant"]


async def test_switch_after_restart_uses_persisted_model_configuration():
    store = MemoryStore()
    initial = _manager(
        FakeClient(response="first"),
        store=store,
        model="model-a",
        effort="low",
    )
    session = initial.create()
    await session.run("first")
    initial.replace_config(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(response="second"),
                context_window=4_000,
                output_reserve=100,
                reserve_tokens=50,
                window_source="catalog",
            ),
            tools=[],
        ),
        model="model-b",
        effort="high",
        context_window=4_000,
    )
    await initial.current.run("second")

    def restore(ref):
        assert ref.model == "model-b"
        return AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(response="restored"),
                context_window=4_000,
                output_reserve=100,
                reserve_tokens=50,
                window_source="catalog",
            ),
            tools=[],
        )

    restarted = SessionManager(
        AgentLoopConfig(model=ChatModelPort(FakeClient(response="wrong")), tools=[]),
        store=store,
        session_config_factory=restore,
    )
    restored = restarted.switch(session.session_id)
    await restored.run("after restart")

    assert restored.context_budget is not None
    assert restored.context_budget.context_window == 4_000


async def test_subscribe_follows_current_across_switch():
    """订阅跟随:切换会话后订阅方无需重新订阅(design D1)。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    seen: list = []
    mgr.subscribe(seen.append)
    a = mgr.create()
    await (a.run("hi"))
    assert EventType.SESSION_STARTED in _event_types(seen)

    b = mgr.create()
    seen.clear()
    await (b.run("hi2"))
    assert EventType.SESSION_STARTED in _event_types(seen)  # 跟随到新会话

    mgr.switch(a.session_id)
    seen.clear()
    a2 = mgr.switch(a.session_id)
    await (a2.run("hi3"))
    assert EventType.SESSION_STARTED in _event_types(seen)  # 跟随回旧会话(重建壳)


async def test_dispose_keeps_file_and_allows_reswitch():
    """dispose:从活动集合移除,文件保留,可再次恢复。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    await (a.run("hi"))
    mgr.dispose(a.session_id)
    assert mgr.current is None
    assert store.get(a.session_id) is not None  # 文件保留
    a2 = mgr.switch(a.session_id)
    assert len(a2.history) == 2  # 可再次恢复


async def test_continue_recent_returns_latest(monkeypatch):
    """continue_recent 返回最近有活动的会话,不依赖真实时钟或固定 sleep。"""
    from codeagent.session.persistence import memory_store

    timestamps = iter(
        (
            "2026-08-27T00:00:00.000Z",
            "2026-08-27T00:00:00.001Z",
            "2026-08-27T00:00:00.002Z",
            "2026-08-27T00:00:00.003Z",
            "2026-08-27T00:00:00.004Z",
            "2026-08-27T00:00:00.005Z",
        )
    )
    monkeypatch.setattr(memory_store, "_now", lambda: next(timestamps))
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    await (a.run("第一轮"))
    b = mgr.create()
    await (b.run("第二轮"))
    assert mgr.continue_recent().session_id == b.session_id


async def test_replace_config_switches_model_and_persists():
    """replace_config:热切换后会话使用新模型,配置写入 store。"""
    store = MemoryStore()
    mgr = _manager(store=store, model="a", effort="low")
    session = mgr.create()
    await (session.run("首轮"))
    new_config = AgentLoopConfig(model=ChatModelPort(FakeClient(response="新配置回复")), tools=[])
    mgr.replace_config(new_config, model="b", effort="high")
    ref = store.list()[-1]
    assert ref.model == "b" and ref.effort == "high"
    # 既有会话继续对话使用新端口(历史不丢、回复来自新模型)
    await (mgr.current.run("继续"))
    assistant = [m.content for m in mgr.current.history if m.role == "assistant"]
    assert assistant[-1] == "新配置回复"


async def test_replace_config_halt_running():
    """replace_config 先中止运行中的会话(避免旧配置执行中被替换)。"""
    mgr = _manager(store=None)
    session = mgr.create()
    new_config = AgentLoopConfig(model=ChatModelPort(FakeClient(response="x")), tools=[])

    async def _scenario() -> None:
        task = asyncio.create_task(asyncio.sleep(10))  # 伪装运行中
        session._current_task = task
        mgr.replace_config(new_config, model="c")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()  # halt 中止了运行中任务
        assert mgr._config is new_config

    await (_scenario())


def test_continue_recent_without_sessions_creates_new():
    """continue_recent:无会话时创建新会话(spec 场景)。"""
    mgr = _manager(store=MemoryStore())
    s = mgr.continue_recent()
    assert s is not None and mgr.current is s


def test_switch_missing_session_raises():
    mgr = _manager(store=MemoryStore())
    with pytest.raises(ValueError, match="会话不存在"):
        mgr.switch("ghost")


async def test_resident_session_limit_evicts_old_shell_but_keeps_persistence():
    """常驻会话有界:淘汰内存壳,不删除可恢复的持久化记录。"""
    store = MemoryStore()
    mgr = _manager(store=store, max_resident_sessions=2)

    first = mgr.create()
    first_id = first.session_id
    await first.run("first")
    second = mgr.create()
    await second.run("second")
    mgr.create()

    assert len(mgr._sessions) == 2
    assert first_id not in mgr._sessions
    assert store.get(first_id) is not None
    restored = mgr.switch(first_id)
    assert restored.session_id == first_id
    assert len(restored.history) == 2


async def test_create_with_parent_session():
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    b = mgr.create(parent_session=a.session_id)
    await (b.run("分支首轮"))
    assert store.get(b.session_id).parent_session == a.session_id


async def test_single_active_run_halted_on_switch():
    """单活语义:创建/切换会话时,运行中的会话被中止并广播 RUN_CANCELLED。

    订阅转移发生在中止广播之前(旧会话事件不再属于 current),所以 manager
    订阅方收不到旧会话的取消事件;abort 契约在旧会话自己的 bus 上仍完整生效。
    """

    started = asyncio.Event()

    class SlowModel(FakeClient):
        async def stream(self, messages, tools=None):
            started.set()
            await asyncio.Event().wait()
            async for ev in super().stream(messages, tools):
                yield ev

    store = MemoryStore()
    mgr = _manager(SlowModel(response="x"), store=store)
    a = mgr.create()
    a_seen: list = []
    a.subscribe(a_seen.append)  # 直接订阅 a:验证中止契约在旧会话上生效

    async def scenario() -> None:
        task = asyncio.create_task(a.run("跑"))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        b = mgr.create()  # 触发 _halt_current → abort a 的运行
        assert mgr.current is b
        with pytest.raises(asyncio.CancelledError):
            await task

    await (scenario())
    assert EventType.RUN_CANCELLED in _event_types(a_seen)
    assert a.history == []  # 取消回滚


async def test_manager_close_waits_for_session_run_to_finish():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowModel(FakeClient):
        async def stream(self, messages, tools=None):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            if False:
                yield None

    manager = _manager(SlowModel(response="x"))
    session = manager.create()
    task = asyncio.create_task(session.run("跑"))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await manager.close()

    assert cancelled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session._runtime.phase.value == "idle"


async def test_async_switch_waits_for_current_run_cleanup():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowModel(FakeClient):
        async def stream(self, messages, tools=None):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            if False:
                yield None

    manager = _manager(SlowModel(response="x"), store=MemoryStore())
    current = manager.create()
    task = asyncio.create_task(current.run("跑"))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    target = await manager.create_async()

    assert cancelled.is_set()
    assert manager.current is target
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_concurrent_manager_close_waits_for_one_shared_close():
    started = asyncio.Event()
    release = asyncio.Event()

    async def close_runtime() -> None:
        started.set()
        await release.wait()

    manager = _manager()
    manager._runtime_closer = close_runtime
    first = asyncio.create_task(manager.close())
    await started.wait()
    second = asyncio.create_task(manager.close())
    await asyncio.sleep(0)

    assert not second.done()
    release.set()
    await asyncio.gather(first, second)


# -- session-fork change:会话分叉 --------------------------------------------


async def _run_rounds(mgr: SessionManager, session, texts: list[str]) -> None:
    """在会话上依次跑几轮(直接经 AgentSession.run,事件驱动)。"""
    for text in texts:
        await session.run(text)


async def test_fork_switches_to_new_session_and_keeps_original():
    """fork:创建分叉会话并切换 current;原会话可切回且历史完整。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    first = mgr.create()
    await _run_rounds(mgr, first, ["第一问", "第二问"])  # 两条 user 消息

    forked = mgr.fork(first.session_id)  # 缺省 = 最近 user 消息(第二问)之前
    assert mgr.current is forked
    assert forked.session_id != first.session_id
    assert [m.content for m in forked.history if m.role == "user"] == ["第一问"]
    # 原会话保留、可切回、历史完整
    back = mgr.switch(first.session_id)
    assert [m.content for m in back.history if m.role == "user"] == ["第一问", "第二问"]
    # 新会话可继续对话
    await _run_rounds(mgr, forked, ["分叉后的新问题"])
    assert [m.content for m in forked.history if m.role == "user"] == ["第一问", "分叉后的新问题"]
    assert [m.content for m in back.history if m.role == "user"] == ["第一问", "第二问"]


async def test_fork_with_explicit_message_id():
    """fork 指定消息 id:从该 user 消息之前分叉。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    await _run_rounds(mgr, session, ["问题一", "问题二", "问题三"])
    first_user = next(m for m in session.history if m.role == "user")
    forked = mgr.fork(session.session_id, first_user.id)  # 从首条 user 消息之前 → 空历史
    assert forked.history == []
    assert forked.session_id != session.session_id


def test_fork_validation_errors():
    """fork 校验:无 store / 会话不存在 / 无 user 消息 → 明确错误。"""
    mgr = _manager(store=None)
    with pytest.raises(ValueError, match="持久化会话"):
        mgr.fork("any")
    store = MemoryStore()
    mgr = _manager(store=store)
    mgr.create()
    with pytest.raises(ValueError, match="会话不存在"):
        mgr.fork("ghost")
    empty = mgr.create()  # 无消息,尚未持久化
    with pytest.raises(ValueError, match="会话不存在"):
        mgr.fork(empty.session_id)


async def test_fork_subscription_follows():
    """分叉后订阅跟随到新会话(订阅方无感;对齐 switch 语义)。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    first = mgr.create()
    await _run_rounds(mgr, first, ["问题一"])
    seen: list = []
    mgr.subscribe(seen.append)
    forked = mgr.fork(first.session_id)
    await _run_rounds(mgr, forked, ["分叉问题"])
    assert any(e.type == EventType.SESSION_STARTED for e in seen)
    assert any(
        e.type == EventType.SESSION_STARTED
        and e.metadata.get("previous_session_id") == first.session_id
        for e in seen
    )


async def test_fork_compacted_session_restores_summary():
    """fork 已压缩会话:新会话恢复摘要状态(回归:此前摘要丢失,上下文信息缺失)。"""
    from codeagent.session.compaction import find_cut_point
    from codeagent.session.persistence import CompactionEntry

    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    texts = [f"问{i}" + "x" * 60 for i in range(6)]
    for t in texts:
        await _run_rounds(mgr, session, [t])
    # 手动压缩(预算内切点):模拟 compact 的 store 侧
    cut = find_cut_point(session.history, budget=80)
    assert cut > 0
    store.append_compaction(
        session.session_id,
        CompactionEntry(
            summary="摘要1",
            parent_id=session.history[-1].id,
            first_kept_entry_id=session.history[cut].id,
        ),
    )
    forked = mgr.fork(session.session_id)
    assert forked._summary == "摘要1"  # 摘要随分叉恢复
    assert forked.history  # 保留窗口消息
    # 精确不变量:分叉保留窗口从压缩切点处原样接续
    # (uuid7 同毫秒随机位使 >= 不成立,此前 or True 恒真糊绿,审计 M-9)
    assert forked.history[0].id == session.history[cut].id
