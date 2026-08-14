"""会话管理器测试(design D1):生命周期、订阅跟随、单活语义、继续最近。"""

from __future__ import annotations

import asyncio

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
    store = MemoryStore()
    mgr = _manager(store=store)
    a = mgr.create()
    asyncio.run(a.run("第一轮"))
    b = mgr.create()
    asyncio.run(b.run("第二轮"))
    assert mgr.continue_recent().session_id == b.session_id


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
