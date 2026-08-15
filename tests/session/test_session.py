"""会话层测试(自研版):事件订阅、会话维度累积、失败/取消回滚、store 落盘、
运行干预(abort/steer/followup)、run_sync 双形态、EventBus 语义。"""

from __future__ import annotations

import asyncio

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.core import AgentPorts, EventType, RecursionLimitError
from codeagent.session import AgentSession, EventBus
from codeagent.session.store import MemoryStore
from codeagent.tools.atomic import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    WriteTool,
)


def _session(model: FakeClient, store=None, session_id: str | None = None) -> AgentSession:
    ports = AgentPorts(
        model=ChatModelPort(model),
        tools=[ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()],
    )
    return AgentSession(ports, EventBus(), store=store, session_id=session_id)


def _event_types(seen) -> list[str]:
    return [e.type for e in seen]


def test_run_returns_none_and_emits_events():
    sess = _session(FakeClient(response="OK"))
    seen: list = []
    sess.subscribe(seen.append)

    assert asyncio.run(sess.run("你好")) is None
    types = _event_types(seen)
    assert EventType.SESSION_STARTED in types
    assert EventType.TEXT_DELTA in types
    assert EventType.TURN_END in types


def test_session_accumulates_context():
    """会话维度累积:第二轮历史含第一轮消息(会话即状态)。"""
    model = FakeClient(responses=["第一轮回复", "第二轮回复"])
    sess = _session(model)
    asyncio.run(sess.run("第一轮"))
    asyncio.run(sess.run("第二轮"))
    roles = [m.role for m in sess.history]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 2


def test_failure_rolls_back_and_emits_error():
    """图级失败:ERROR 事件 + 历史回滚到本轮前,会话可继续。"""

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("图炸了")

    sess = _session(BoomModel(response="x"))
    seen: list = []
    sess.subscribe(seen.append)
    asyncio.run(sess.run("触发"))
    assert EventType.ERROR in _event_types(seen)
    assert [e.payload for e in seen if e.type == EventType.ERROR][0] == "图炸了"
    assert sess.history == []  # 本轮消息已回滚

    # 会话可继续
    sess2 = _session(FakeClient(response="ok"))
    asyncio.run(sess2.run("继续"))
    assert [m.role for m in sess2.history] == ["user", "assistant"]


def test_recursion_error_friendly_message():
    """递归超限:ERROR 事件带友好提示,历史回滚。"""
    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo x"}, "id": f"r{i}", "type": "tool_call"}]}
            for i in range(10)
        ]
    )
    sess = _session(model)
    seen: list = []
    sess.subscribe(seen.append)
    asyncio.run(sess.run("循环", recursion_limit=2))
    error = next(e for e in seen if e.type == EventType.ERROR)
    assert "次数过多" in str(error.payload)
    assert sess.history == []


def test_abort_cancels_and_emits_run_cancelled():
    """abort:取消当前 run,RUN_CANCELLED 事件 + 历史回滚。"""

    class SlowModel(FakeClient):
        async def stream(self, messages, tools=None):
            await asyncio.sleep(2)  # 慢速:让 abort 在运行中生效
            async for ev in super().stream(messages, tools):
                yield ev

    sess = _session(SlowModel(response="x"))
    seen: list = []
    sess.subscribe(seen.append)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        await asyncio.sleep(0.05)
        sess.abort()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert EventType.RUN_CANCELLED in _event_types(seen)
    assert sess.history == []


def test_steer_injects_message():
    """运行中 steer:注入消息成为后续轮次的 user 消息(回归:时序确定性)。

    早期缺陷:注入依赖 50ms sleep 恰好落在工具执行窗口,快速机器上整轮
    run 早于 sleep 完成(实测 12ms vs 50ms),注入队列永不消费。现在第一轮
    模型调用固定放慢 0.2s,steer 在 0.05s 入队必然落在运行中;并断言注入
    消息进入第二轮模型输入(而非仅追加在历史末尾)。
    """

    class SlowFirstModel(FakeClient):
        """放慢每次模型调用:让 steer 必然落在第一轮调用期间。"""

        async def stream(self, messages, tools=None):
            await asyncio.sleep(0.2)
            async for ev in super().stream(messages, tools):
                yield ev

    model = SlowFirstModel(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo a"}, "id": "s1", "type": "tool_call"}]},
            {"content": "已处理注入"},
        ]
    )
    sess = _session(model)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("开始"))
        await asyncio.sleep(0.05)  # 第一轮模型调用进行中(0.05 < 0.2)
        sess.steer("运行中注入")
        await task

    asyncio.run(scenario())
    users = [m.content for m in sess.history if m.role == "user"]
    assert "运行中注入" in users
    # 注入消息进入第二轮模型输入(下一轮循环前消费,而非事后追加)
    second_call = model.call_history[1]["messages"]
    assert any("运行中注入" in (m.get("content") or "") for m in second_call)


def test_followup_continues_history():
    """结束后续跑:followup 在既有历史之上再跑一轮,上下文连续。"""
    model = FakeClient(responses=["第一轮回复", "后续回复"])
    sess = _session(model)
    seen: list = []
    sess.subscribe(seen.append)
    asyncio.run(sess.run("第一轮"))
    asyncio.run(sess.followup("后续"))
    assert [m.role for m in sess.history] == ["user", "assistant", "user", "assistant"]
    assert [m.content for m in sess.history if m.role == "user"] == ["第一轮", "后续"]
    # 第二轮模型输入含第一轮上下文(会话即状态,不重建会话)
    assert model.call_history[1]["messages"][0]["content"] == "第一轮"
    assert EventType.TURN_END in _event_types(seen)


def test_store_persists_successful_turns_only():
    """store 落盘:成功轮次的消息写入;失败轮次不写入(append-only 回滚语义)。"""
    store = MemoryStore()
    sess = _session(FakeClient(response="第一轮"), store=store, session_id="s1")
    asyncio.run(sess.run("你好"))
    assert len(store.load_messages("s1")) == 2  # user + assistant

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("炸")

    sess2 = _session(BoomModel(response="x"), store=store, session_id="s1")
    asyncio.run(sess2.run("会失败"))
    # 失败轮次未落盘,历史仍为前一轮的 2 条
    assert len(store.load_messages("s1")) == 2


def test_session_restores_from_store():
    """恢复:既有 session_id + store → 历史恢复,继续对话追加同一会话。"""
    store = MemoryStore()
    first = _session(FakeClient(response="第一轮"), store=store, session_id="s1")
    asyncio.run(first.run("你好"))
    assert first.session_id == "s1"

    second = _session(FakeClient(response="第二轮"), store=store, session_id="s1")
    assert [m.role for m in second.history] == ["user", "assistant"]
    asyncio.run(second.run("继续"))
    assert len(store.load_messages("s1")) == 4


def test_run_sync_without_loop_completes():
    sess = _session(FakeClient(response="OK"))
    seen: list = []
    sess.subscribe(seen.append)
    sess.run_sync("你好")
    assert EventType.TURN_END in _event_types(seen)


def test_run_sync_inside_running_loop_does_not_raise():
    """已有运行中事件循环的线程调用 run_sync 不抛 RuntimeError(回归:P2-7)。"""
    sess = _session(FakeClient(response="OK"))

    async def scenario() -> None:
        await asyncio.to_thread(sess.run_sync, "你好")

    asyncio.run(scenario())


def test_run_sync_graph_error_becomes_error_event():
    """run_sync 下与 run 语义一致:图异常转成 ERROR 事件而非向上抛。"""

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("图炸了")

    sess = _session(BoomModel(response="x"))
    seen: list = []
    sess.subscribe(seen.append)
    sess.run_sync("触发")
    assert EventType.ERROR in _event_types(seen)


def test_friendly_error_classifies_http_and_network_errors():
    from codeagent.session.session import AgentSession

    def friendly(exc: Exception) -> str:
        return AgentSession._friendly_error(exc)

    import httpx

    assert "认证失败" in friendly(httpx.HTTPStatusError("e", request=httpx.Request("GET", "http://x"), response=httpx.Response(401)))
    assert "过于频繁" in friendly(httpx.HTTPStatusError("e", request=httpx.Request("GET", "http://x"), response=httpx.Response(429)))
    assert "超时" in friendly(httpx.TimeoutException("t"))
    assert "连接" in friendly(httpx.ConnectError("c"))
    assert "次数过多" in friendly(RecursionLimitError())
    assert friendly(RuntimeError("别的")) == "别的"


# ── EventBus(保留 v0.1 语义)────────────────────────────────────────

def test_event_bus_multiple_subscribers():
    bus = EventBus()
    a, b = [], []
    bus.subscribe(a.append)
    bus.subscribe(b.append)
    from codeagent.core.events import AgentEvent

    bus.emit(AgentEvent("x"))
    assert len(a) == 1 and len(b) == 1


def test_event_bus_unsubscribe():
    bus = EventBus()
    seen: list = []
    unsub = bus.subscribe(seen.append)
    unsub()
    from codeagent.core.events import AgentEvent

    bus.emit(AgentEvent("x"))
    assert seen == []


def test_event_bus_subscriber_exception_does_not_break_others():
    bus = EventBus()
    seen: list = []
    bus.subscribe(lambda ev: (_ for _ in ()).throw(RuntimeError("订阅方炸了")))
    bus.subscribe(seen.append)
    from codeagent.core.events import AgentEvent

    bus.emit(AgentEvent("x"))
    assert len(seen) == 1
    assert len(bus.emit_errors) == 1


def test_event_bus_clear_resets_errors():
    bus = EventBus()
    from codeagent.core.events import AgentEvent

    bus.subscribe(lambda ev: (_ for _ in ()).throw(RuntimeError("炸")))
    bus.emit(AgentEvent("x"))
    assert len(bus.emit_errors) == 1
    bus.clear()
    assert bus.emit_errors == []
