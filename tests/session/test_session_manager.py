"""会话管理器测试(design D1):生命周期、订阅跟随、单活语义、继续最近。"""

from __future__ import annotations

import asyncio
import time

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import AgentPorts, EventType
from codeagent.session import SessionManager
from codeagent.session.store import MemoryStore


def _manager(client: FakeClient | None = None, store=None, **kwargs) -> SessionManager:
    ports = AgentPorts(model=ChatModelPort(client or FakeClient(response="OK")), tools=[])
    return SessionManager(ports, store=store, **kwargs)


def _event_types(seen) -> list[str]:
    return [e.type for e in seen]


def test_create_sets_current_and_persists_header():
    store = MemoryStore()
    mgr = _manager(store=store, model="deepseek-v4-flash", effort="high")
    a = mgr.create()
    assert mgr.current is a
    assert len(store.list()) == 1
    ref = store.get(a.session_id)
    assert ref.model == "deepseek-v4-flash" and ref.effort == "high"


def test_switch_restores_history():
    """switch:恢复既有会话历史,新消息追加到同一会话。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    asyncio.run(a.run("第一轮"))
    b = mgr.create()
    assert mgr.current is b
    a2 = mgr.switch(a.session_id)
    assert [m.role for m in a2.history] == ["user", "assistant"]


def test_subscribe_follows_current_across_switch():
    """订阅跟随:切换会话后订阅方无需重新订阅(design D1)。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    seen: list = []
    mgr.subscribe(seen.append)
    a = mgr.create()
    asyncio.run(a.run("hi"))
    assert EventType.SESSION_STARTED in _event_types(seen)

    b = mgr.create()
    seen.clear()
    asyncio.run(b.run("hi2"))
    assert EventType.SESSION_STARTED in _event_types(seen)  # 跟随到新会话

    mgr.switch(a.session_id)
    seen.clear()
    a2 = mgr.switch(a.session_id)
    asyncio.run(a2.run("hi3"))
    assert EventType.SESSION_STARTED in _event_types(seen)  # 跟随回旧会话(重建壳)


def test_dispose_keeps_file_and_allows_reswitch():
    """dispose:从活动集合移除,文件保留,可再次恢复。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    asyncio.run(a.run("hi"))
    mgr.dispose(a.session_id)
    assert mgr.current is None
    assert store.get(a.session_id) is not None  # 文件保留
    a2 = mgr.switch(a.session_id)
    assert len(a2.history) == 2  # 可再次恢复


def test_continue_recent_returns_latest():
    """continue_recent 返回最近创建的会话(回归:时序确定性)。

    早期缺陷:store 时间戳为毫秒精度,两次紧邻 create 落在同一毫秒时列表按
    uuid 兜底排序,"最近"断言不确定(全量测试负载下偶发失败)。两次创建间
    留 2ms 间隔,保证时间戳必然不同,断言与实现语义(时间升序取末位)一致。
    """
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    asyncio.run(a.run("第一轮"))
    time.sleep(0.002)  # 跨过毫秒时间戳精度,保证 a/b 排序确定
    b = mgr.create()
    asyncio.run(b.run("第二轮"))
    assert mgr.continue_recent().session_id == b.session_id


def test_replace_ports_switches_config_and_persists():
    """replace_ports:热切换后会话用新端口,配置写入 store(读侧后写覆盖)。"""
    store = MemoryStore()
    mgr = _manager(store=store, model="a", effort="low")
    mgr.create()
    new_ports = AgentPorts(model=ChatModelPort(FakeClient(response="新配置回复")), tools=[])
    mgr.replace_ports(new_ports, model="b", effort="high")
    ref = store.list()[-1]
    assert ref.model == "b" and ref.effort == "high"
    # 既有会话继续对话使用新端口(历史不丢、回复来自新模型)
    asyncio.run(mgr.current.run("继续"))
    assistant = [m.content for m in mgr.current.history if m.role == "assistant"]
    assert assistant[-1] == "新配置回复"


def test_replace_ports_halt_running():
    """replace_ports 先中止运行中的会话(避免旧端口执行中被替换)。"""
    mgr = _manager(store=MemoryStore())
    session = mgr.create()
    new_ports = AgentPorts(model=ChatModelPort(FakeClient(response="x")), tools=[])

    async def _scenario() -> None:
        task = asyncio.create_task(asyncio.sleep(10))  # 伪装运行中
        session._current_task = task
        mgr.replace_ports(new_ports, model="c")
        await asyncio.sleep(0)  # 让取消在事件循环中生效
        assert task.cancelled()  # halt 中止了运行中任务
        assert mgr._ports is new_ports

    asyncio.run(_scenario())


def test_continue_recent_without_sessions_creates_new():
    """continue_recent:无会话时创建新会话(spec 场景)。"""
    mgr = _manager(store=MemoryStore())
    s = mgr.continue_recent()
    assert s is not None and mgr.current is s


def test_switch_missing_session_raises():
    mgr = _manager(store=MemoryStore())
    with pytest.raises(ValueError, match="会话不存在"):
        mgr.switch("ghost")


def test_create_with_parent_session():
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    b = mgr.create(parent_session=a.session_id)
    assert store.get(b.session_id).parent_session == a.session_id


def test_single_active_run_halted_on_switch():
    """单活语义:创建/切换会话时,运行中的会话被中止并广播 RUN_CANCELLED。

    订阅转移发生在中止广播之前(旧会话事件不再属于 current),所以 manager
    订阅方收不到旧会话的取消事件;abort 契约在旧会话自己的 bus 上仍完整生效。
    """

    class SlowModel(FakeClient):
        async def stream(self, messages, tools=None):
            await asyncio.sleep(2)  # 慢速:让 abort 在运行中生效
            async for ev in super().stream(messages, tools):
                yield ev

    store = MemoryStore()
    mgr = _manager(SlowModel(response="x"), store=store)
    a = mgr.create()
    a_seen: list = []
    a.subscribe(a_seen.append)  # 直接订阅 a:验证中止契约在旧会话上生效

    async def scenario() -> None:
        task = asyncio.create_task(a.run("跑"))
        await asyncio.sleep(0.05)
        b = mgr.create()  # 触发 _halt_current → abort a 的运行
        assert mgr.current is b
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert EventType.RUN_CANCELLED in _event_types(a_seen)
    assert a.history == []  # 取消回滚


# -- session-fork change:会话分叉 --------------------------------------------


def _run_rounds(mgr: SessionManager, session, texts: list[str]) -> None:
    """在会话上依次跑几轮(直接经 AgentSession.run,事件驱动)。"""
    for text in texts:
        asyncio.run(session.run(text))


def test_fork_switches_to_new_session_and_keeps_original():
    """fork:创建分叉会话并切换 current;原会话可切回且历史完整。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    first = mgr.create()
    _run_rounds(mgr, first, ["第一问", "第二问"])  # 两条 user 消息

    forked = mgr.fork(first.session_id)  # 缺省 = 最近 user 消息(第二问)之前
    assert mgr.current is forked
    assert forked.session_id != first.session_id
    assert [m.content for m in forked.history if m.role == "user"] == ["第一问"]
    # 原会话保留、可切回、历史完整
    back = mgr.switch(first.session_id)
    assert [m.content for m in back.history if m.role == "user"] == ["第一问", "第二问"]
    # 新会话可继续对话
    _run_rounds(mgr, forked, ["分叉后的新问题"])
    assert [m.content for m in forked.history if m.role == "user"] == ["第一问", "分叉后的新问题"]
    assert [m.content for m in back.history if m.role == "user"] == ["第一问", "第二问"]


def test_fork_with_explicit_message_id():
    """fork 指定消息 id:从该 user 消息之前分叉。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    _run_rounds(mgr, session, ["问题一", "问题二", "问题三"])
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
    empty = mgr.create()  # 无消息
    with pytest.raises(ValueError, match="没有可分叉的用户消息"):
        mgr.fork(empty.session_id)


def test_fork_subscription_follows():
    """分叉后订阅跟随到新会话(订阅方无感;对齐 switch 语义)。"""
    store = MemoryStore()
    mgr = _manager(store=store)
    first = mgr.create()
    _run_rounds(mgr, first, ["问题一"])
    seen: list = []
    mgr.subscribe(seen.append)
    forked = mgr.fork(first.session_id)
    _run_rounds(mgr, forked, ["分叉问题"])
    assert any(e.type == EventType.SESSION_STARTED for e in seen)
    assert any(
        e.type == EventType.SESSION_STARTED
        and e.metadata.get("previous_session_id") == first.session_id
        for e in seen
    )


def test_fork_compacted_session_restores_summary():
    """fork 已压缩会话:新会话恢复摘要状态(回归:此前摘要丢失,上下文信息缺失)。"""
    from codeagent.session.compaction import find_cut_point
    from codeagent.session.store import CompactionEntry

    store = MemoryStore()
    mgr = _manager(store=store)
    session = mgr.create()
    texts = [f"问{i}" + "x" * 60 for i in range(6)]
    for t in texts:
        _run_rounds(mgr, session, [t])
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
