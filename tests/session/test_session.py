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


def test_session_scopes_all_events_to_one_run():
    sess = _session(FakeClient(response="OK"), session_id="session-1")
    seen: list = []
    sess.subscribe(seen.append)

    asyncio.run(sess.run("你好"))

    run_ids = {event.metadata.get("run_id") for event in seen}
    session_ids = {event.metadata.get("session_id") for event in seen}
    assert len(run_ids) == 1 and None not in run_ids
    assert session_ids == {"session-1"}
    assert all(event.metadata["run_id"] for event in seen)


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


def test_model_failure_can_be_retried_without_copying_tool_history():
    class FlakyModel(FakeClient):
        def __init__(self):
            super().__init__(response="ok")
            self.failed = True

        def _generate(self, messages, **kwargs):
            if self.failed:
                self.failed = False
                raise RuntimeError("temporary")
            return super()._generate(messages, **kwargs)

    sess = _session(FlakyModel())
    seen: list = []
    sess.subscribe(seen.append)
    asyncio.run(sess.run("retry me"))
    assert sess.last_failure is not None and sess.last_failure["retryable"] is True
    asyncio.run(sess.retry())
    assert [message.content for message in sess.history if message.role == "user"] == [
        "retry me"
    ]
    assert EventType.RETRY_STARTED in _event_types(seen)


def test_side_effect_failure_is_not_automatically_retryable():
    sess = _session(FakeClient(response="ok"))
    sess._last_failure = {
        "error": "tool uncertain",
        "retryable": False,
        "side_effect_state": "uncertain",
        "cleanup_uncertain": True,
        "prompt": "old",
    }
    with pytest.raises(ValueError, match="不可安全重试"):
        asyncio.run(sess.retry())


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


def test_session_restores_latest_context_tokens_from_store():
    """恢复持久化会话时,状态栏所需的最近上下文占用也应恢复。"""
    store = MemoryStore()
    first = _session(
        FakeClient(response="第一轮", usage={"input_tokens": 12_400, "output_tokens": 20}),
        store=store,
        session_id="s1",
    )
    asyncio.run(first.run("你好"))

    second = _session(
        FakeClient(response="第二轮"),
        store=store,
        session_id="s1",
    )
    assert second.context_tokens == 12_400


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

    auth_msg = friendly(
        httpx.HTTPStatusError(
            "e", request=httpx.Request("GET", "http://x"), response=httpx.Response(401)
        )
    )
    assert "认证失败" in auth_msg
    # (tui-login-command)认证失败文案带 /login 引导
    assert "/login" in auth_msg
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


# -- 确认响应(security-permissions)------------------------------------------


class _StubPolicy:
    """脚本化策略:按工具名返回预设动作(会话层测试用,与 core 测试同形)。"""

    def __init__(self, action_by_tool: dict[str, str]) -> None:
        self._action_by_tool = action_by_tool

    def decide(self, tool_name: str, args: dict):
        from codeagent.core.ports import PolicyDecision

        return PolicyDecision(
            self._action_by_tool.get(tool_name, "allow"), reason=f"stub:{tool_name}"
        )


def _session_with_policy(
    model: FakeClient, policy=None, store=None, session_id: str | None = None
) -> AgentSession:
    ports = AgentPorts(
        model=ChatModelPort(model),
        tools=[ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()],
        policy=policy,
    )
    return AgentSession(ports, EventBus(), store=store, session_id=session_id)


def _ask_model() -> FakeClient:
    """单轮 bash echo ok 后回复的 FakeClient(ask 路径用)。"""
    return FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "bash", "args": {"command": "echo ok"}, "id": "c1", "type": "tool_call"}
                ],
            },
            {"content": "完成"},
        ]
    )


async def _wait_for_confirmation(seen: list, timeout: int = 200) -> dict:
    """轮询等待 confirmation_requested 事件,返回其 payload(须在运行中循环内 await)。"""
    for _ in range(timeout):
        if any(e.type == EventType.CONFIRMATION_REQUESTED for e in seen):
            return next(e for e in seen if e.type == EventType.CONFIRMATION_REQUESTED).payload
        await asyncio.sleep(0.005)
    raise AssertionError("未收到确认请求事件")


def test_respond_approval_approves_and_executes():
    """批准:确认请求事件先于工具结果;响应后工具执行、结果非错误。"""
    sess = _session_with_policy(_ask_model(), policy=_StubPolicy({"bash": "ask"}))
    seen: list = []
    sess.subscribe(seen.append)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        payload = await _wait_for_confirmation(seen)
        assert payload["tool"] == "bash" and payload["reason"] == "stub:bash"
        assert not any(e.type == EventType.TOOL_RESULT for e in seen)  # 未响应前不执行
        sess.respond_approval(payload["request_id"], True)
        await task

    asyncio.run(scenario())
    results = [e for e in seen if e.type == EventType.TOOL_RESULT]
    assert results and results[-1].metadata["error"] is False
    assert "ok" in results[-1].payload


def test_respond_approval_rejects_and_fills_error():
    """拒绝:工具不执行,结果回填「用户拒绝执行」错误(模型可见)。"""
    sess = _session_with_policy(_ask_model(), policy=_StubPolicy({"bash": "ask"}))
    seen: list = []
    sess.subscribe(seen.append)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        payload = await _wait_for_confirmation(seen)
        sess.respond_approval(payload["request_id"], False)
        await task

    asyncio.run(scenario())
    results = [e for e in seen if e.type == EventType.TOOL_RESULT]
    assert results and results[-1].metadata["error"] is True
    assert "用户拒绝执行" in results[-1].payload
    assert "ok" not in results[-1].payload


def test_abort_while_waiting_confirmation_cancels_without_hanging():
    """等待确认期间 abort:无悬挂,取消语义收尾,工具未执行。"""
    sess = _session_with_policy(_ask_model(), policy=_StubPolicy({"bash": "ask"}))
    seen: list = []
    sess.subscribe(seen.append)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        await _wait_for_confirmation(seen)
        sess.abort()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert EventType.RUN_CANCELLED in [e.type for e in seen]
    assert not any(e.type == EventType.TOOL_RESULT for e in seen)


# -- 会话分叉来源标记(session-fork)-------------------------------------------


def test_forked_session_started_carries_previous_session_id():
    """分叉会话首轮 SESSION_STARTED 事件 metadata 携带父会话 id(对齐 Pi reason=fork)。"""
    ports = AgentPorts(
        model=ChatModelPort(FakeClient(response="OK")),
        tools=[ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()],
    )
    sess = AgentSession(ports, EventBus(), previous_session_id="parent-1")
    seen: list = []
    sess.subscribe(seen.append)
    asyncio.run(sess.run("你好"))
    started = next(e for e in seen if e.type == EventType.SESSION_STARTED)
    assert started.metadata.get("previous_session_id") == "parent-1"
    assert started.payload == "你好"  # payload 语义不变


def test_normal_session_started_has_no_previous_session_id():
    """普通会话首轮 SESSION_STARTED 不携带父会话字段(既有行为不变)。"""
    sess = _session(FakeClient(response="OK"))
    seen: list = []
    sess.subscribe(seen.append)
    asyncio.run(sess.run("你好"))
    started = next(e for e in seen if e.type == EventType.SESSION_STARTED)
    assert "previous_session_id" not in started.metadata


# -- 上下文压缩(session-compaction)-------------------------------------------


def _long(text: str) -> str:
    """长文本输入(每条消息 ≈ 25 token,配合预算 50 触发压缩)。"""
    return text + "x" * 100


class _StubSummarizer:
    """桩摘要:记录调用(窗口 / 既有摘要),返回可断言的拼接文本。"""

    def __init__(self) -> None:
        self.calls: list[tuple[list, str | None]] = []

    async def summarize(self, messages, prev_summary):
        self.calls.append((list(messages), prev_summary))
        window = "|".join(m.content[:6] for m in messages if m.content)
        return f"SUM[{window}]" + (f"<{prev_summary}>" if prev_summary else "")


class _FailingSummarizer:
    async def summarize(self, messages, prev_summary):
        raise RuntimeError("摘要服务失败")


def _compact_session(
    model: FakeClient,
    store=None,
    summarizer=None,
    context_window: int = 128_000,
    compact_budget: int = 50,
) -> AgentSession:
    """构造带 Summarizer 的会话(port 直装,不跨组合根;预算注入小值便于离线测)。"""
    ports = AgentPorts(
        model=ChatModelPort(model),
        tools=[ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()],
    )
    return AgentSession(
        ports,
        EventBus(),
        store=store,
        summarizer=summarizer,
        context_window=context_window,
        compact_budget=compact_budget,
    )


def test_compact_summarizes_and_truncates_history():
    """手动压缩:摘要窗口 → 截断历史 → entry 落盘(store 与内存一致)。"""
    store = MemoryStore()
    model = FakeClient(responses=["答1", "答2", "答3"])
    sess = _compact_session(model, store=store, summarizer=_StubSummarizer())
    for text in (_long("问1"), _long("问2"), _long("问3")):
        asyncio.run(sess.run(text))
    assert len(sess.history) >= 6  # 3 user + 3 assistant
    before_full = len(store.load_messages(sess.session_id))
    history_before_compact = len(sess.history)

    async def scenario() -> None:
        return await sess.compact()

    assert asyncio.run(scenario()) is True
    assert sess._summary is not None and sess._summary.startswith("SUM[")
    # 真截断:历史收缩而非仅非空(此前仅 assert truthy,压缩空转也通过,审计 M-9 同批)
    assert 0 < len(sess.history) < history_before_compact
    assert len(store.load_messages(sess.session_id)) == before_full  # 物理保留
    state = store.load_context(sess.session_id)
    assert state.summary == sess._summary
    assert state.entry_id == sess._summary_entry_id
    assert [m.id for m in state.messages] == [m.id for m in sess.history]


def test_compact_noop_when_all_kept():
    """短历史全部保留:压缩返回 False,无 entry 落盘。"""
    store = MemoryStore()
    sess = _compact_session(FakeClient(response="答"), store=store, summarizer=_StubSummarizer())
    asyncio.run(sess.run("问"))
    assert asyncio.run(sess.compact()) is False
    assert sess._summary is None


def test_compact_without_summarizer_raises():
    """未注入 Summarizer → 明确报错(压缩不可用)。"""
    sess = _compact_session(FakeClient(response="答"))
    with pytest.raises(ValueError, match="压缩不可用"):
        asyncio.run(sess.compact())


def test_compact_failure_emits_terminal_finished_event():
    sess = _compact_session(
        FakeClient(response="答"), summarizer=_FailingSummarizer(), compact_budget=50
    )
    for text in (_long("问1"), _long("问2"), _long("问3")):
        asyncio.run(sess.run(text))
    seen: list = []
    sess.subscribe(seen.append)

    with pytest.raises(RuntimeError, match="摘要服务失败"):
        asyncio.run(sess.compact())

    finished = [event for event in seen if event.type == EventType.COMPACTION_FINISHED]
    assert finished and finished[-1].metadata["success"] is False
    assert finished[-1].metadata["error_code"] == "compaction_failed"


def test_after_compact_run_injects_summary_and_links_parent():
    """压缩后继续对话:摘要注入模型输入;新 user 消息父级接回压缩记录;
    虚拟摘要消息不落盘。"""
    store = MemoryStore()
    model = FakeClient(responses=["答1", "答2", "答3", "答4"])
    sess = _compact_session(model, store=store, summarizer=_StubSummarizer())
    for text in (_long("问1"), _long("问2"), _long("问3")):
        asyncio.run(sess.run(text))
    assert asyncio.run(sess.compact()) is True
    entry_id = sess._summary_entry_id
    # 保留消息的内部链不被改写(物理历史完整)
    kept_user = next(m for m in sess.history if m.role == "user")
    assert kept_user.parent_id != entry_id
    model.call_history.clear()
    asyncio.run(sess.run(_long("问4")))
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


def test_threshold_auto_compact_triggers():
    """阈值触发:usage.input_tokens 超窗口减余量 → turn_end 后自动压缩。"""
    store = MemoryStore()
    # input_tokens 5000 > 20000 - 16384 = 3616 → 触发
    model = FakeClient(
        usage={"input_tokens": 5000, "output_tokens": 10},
        responses=["答1", "答2", "答3", "答4", "答5", "答6"],
    )
    sess = _compact_session(model, store=store, summarizer=_StubSummarizer(), context_window=20000)
    for text in (_long("问1"), _long("问2"), _long("问3"), _long("问4"), _long("问5"), _long("问6")):
        asyncio.run(sess.run(text))
    assert sess._summary is not None  # 自动压缩已发生
    assert store.load_context(sess.session_id).summary == sess._summary


def test_context_usage_properties_expose_latest_input_and_window():
    """会话暴露最近一次输入 token 与上下文窗口,不返回累计 usage。"""
    sess = _compact_session(
        FakeClient(response="答"),
        context_window=32_000,
    )

    assert sess.context_tokens is None
    assert sess.context_window == 32_000
    sess._last_input_tokens = 1_240
    assert sess.context_tokens == 1_240


def test_second_compact_incremental_merge():
    """二次压缩:桩摘要收到既有摘要(增量合并);摘要链 compaction1 → compaction2。"""
    store = MemoryStore()
    model = FakeClient(responses=[f"答{i}" for i in range(8)])
    summarizer = _StubSummarizer()
    sess = _compact_session(model, store=store, summarizer=summarizer)
    for text in (_long("问1"), _long("问2"), _long("问3"), _long("问4")):
        asyncio.run(sess.run(text))
    assert asyncio.run(sess.compact()) is True
    first_entry = sess._summary_entry_id
    first_summary = sess._summary
    for text in (_long("问5"), _long("问6"), _long("问7"), _long("问8")):
        asyncio.run(sess.run(text))
    assert asyncio.run(sess.compact()) is True
    # 二次压缩:既有摘要传入(增量合并,桩拼接 <prev>)
    assert summarizer.calls[-1][1] == first_summary
    assert first_summary in sess._summary
    # 摘要链:new entry 的 parentId = 旧 entry id
    _, second = store._compactions[-1]
    assert second.parent_id == first_entry
    state = store.load_context(sess.session_id)
    assert state.entry_id != first_entry  # 新 entry
    assert state.summary == sess._summary


# -- usage 落库(cost-transparency)---------------------------------------------


def test_successful_run_persists_usage():
    """成功轮:本轮聚合 usage(input/output/reasoning/cached)落库。"""
    store = MemoryStore()
    model = FakeClient(
        usage={
            "input_tokens": 100,
            "output_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 60},
        },
        responses=["回复"],
    )
    sess = _session(model, store=store)
    asyncio.run(sess.run("hi"))
    total = store.load_usage(sess.session_id)
    assert total.input_tokens == 100
    assert total.output_tokens == 20
    assert total.cached_tokens == 60
    assert total.reasoning_tokens == 0


def test_usage_aggregates_across_turns():
    """多轮成功:usage 跨轮累计(第二轮在首轮之上累加)。"""
    store = MemoryStore()
    model = FakeClient(
        usage={"input_tokens": 50, "output_tokens": 10},
        responses=["答1", "答2"],
    )
    sess = _session(model, store=store)
    asyncio.run(sess.run("问1"))
    asyncio.run(sess.run("问2"))
    total = store.load_usage(sess.session_id)
    assert total.input_tokens == 100
    assert total.output_tokens == 20


def test_failed_turn_does_not_persist_usage():
    """失败轮:usage 不落库(与"未完成轮次永不落盘"同承诺)。"""
    store = MemoryStore()
    model = FakeClient(usage={"input_tokens": 99, "output_tokens": 1}, responses=["x"])
    sess = _session(model, store=store)
    # 强制失败:第一轮跑成功后清空 store,再用坏模型触发失败轮
    asyncio.run(sess.run("成功"))
    assert store.load_usage(sess.session_id).input_tokens == 99

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("boom")

    sess2 = _session(BoomModel(response="x"), store=store, session_id=sess.session_id)
    asyncio.run(sess2.run("触发"))
    # 失败轮不追加:聚合仍是成功轮的值
    assert store.load_usage(sess.session_id).input_tokens == 99
    assert store.load_usage(sess.session_id).output_tokens == 1
