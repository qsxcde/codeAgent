"""runtime behavior tests."""

from tests.session.behavior.fixtures import *  # noqa: F401,F403


async def test_run_returns_none_and_emits_events():
    sess = _session(FakeClient(response="OK"))
    seen: list = []
    sess.subscribe(seen.append)

    assert await (sess.run("你好")) is None
    types = _event_types(seen)
    assert EventType.SESSION_STARTED in types
    assert EventType.TEXT_DELTA in types
    assert EventType.TURN_END in types



async def test_session_scopes_all_events_to_one_run():
    sess = _session(FakeClient(response="OK"), session_id="session-1")
    seen: list = []
    sess.subscribe(seen.append)

    await (sess.run("你好"))

    run_ids = {event.metadata.get("run_id") for event in seen}
    session_ids = {event.metadata.get("session_id") for event in seen}
    assert len(run_ids) == 1 and None not in run_ids
    assert session_ids == {"session-1"}
    assert all(event.metadata["run_id"] for event in seen)



async def test_session_accumulates_context():
    """会话维度累积:第二轮历史含第一轮消息(会话即状态)。"""
    model = FakeClient(responses=["第一轮回复", "第二轮回复"])
    sess = _session(model)
    await (sess.run("第一轮"))
    await (sess.run("第二轮"))
    roles = [m.role for m in sess.history]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 2



async def test_failure_rolls_back_and_emits_error():
    """图级失败:ERROR 事件 + 历史回滚到本轮前,会话可继续。"""

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("图炸了")

    sess = _session(BoomModel(response="x"))
    seen: list = []
    sess.subscribe(seen.append)
    await (sess.run("触发"))
    assert EventType.ERROR in _event_types(seen)
    assert [e.payload for e in seen if e.type == EventType.ERROR][0] == "图炸了"
    assert sess.history == []  # 本轮消息已回滚

    # 会话可继续
    sess2 = _session(FakeClient(response="ok"))
    await (sess2.run("继续"))
    assert [m.role for m in sess2.history] == ["user", "assistant"]



async def test_model_failure_can_be_retried_without_copying_tool_history():
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
    await (sess.run("retry me"))
    assert sess.last_failure is not None and sess.last_failure["retryable"] is True
    await (sess.retry())
    assert [message.content for message in sess.history if message.role == "user"] == [
        "retry me"
    ]
    assert EventType.RETRY_STARTED in _event_types(seen)



async def test_side_effect_failure_is_not_automatically_retryable():
    sess = _session(FakeClient(response="ok"))
    sess._last_failure = {
        "error": "tool uncertain",
        "retryable": False,
        "side_effect_state": "uncertain",
        "cleanup_uncertain": True,
        "prompt": "old",
    }
    with pytest.raises(ValueError, match="不可安全重试"):
        await (sess.retry())



async def test_recursion_error_friendly_message():
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
    await (sess.run("循环", recursion_limit=2))
    error = next(e for e in seen if e.type == EventType.ERROR)
    assert "次数过多" in str(error.payload)
    assert sess.history == []



async def test_store_persists_successful_turns_only():
    """store 落盘:成功轮次的消息写入;失败轮次不写入(append-only 回滚语义)。"""
    store = MemoryStore()
    sess = _session(FakeClient(response="第一轮"), store=store, session_id="s1")
    await (sess.run("你好"))
    assert len(store.load_messages("s1")) == 2  # user + assistant

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("炸")

    sess2 = _session(BoomModel(response="x"), store=store, session_id="s1")
    await (sess2.run("会失败"))
    # 失败轮次未落盘,历史仍为前一轮的 2 条
    assert len(store.load_messages("s1")) == 2



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



def test_event_bus_multiple_subscribers():
    bus = EventBus()
    a, b = [], []
    bus.subscribe(a.append)
    bus.subscribe(b.append)
    from codeagent.core.contracts.events import AgentEvent

    bus.emit(AgentEvent("x"))
    assert len(a) == 1 and len(b) == 1



def test_event_bus_unsubscribe():
    bus = EventBus()
    seen: list = []
    unsub = bus.subscribe(seen.append)
    unsub()
    from codeagent.core.contracts.events import AgentEvent

    bus.emit(AgentEvent("x"))
    assert seen == []



def test_event_bus_subscriber_exception_does_not_break_others():
    bus = EventBus()
    seen: list = []
    bus.subscribe(lambda ev: (_ for _ in ()).throw(RuntimeError("订阅方炸了")))
    bus.subscribe(seen.append)
    from codeagent.core.contracts.events import AgentEvent

    bus.emit(AgentEvent("x"))
    assert len(seen) == 1
    assert len(bus.emit_errors) == 1



def test_event_bus_clear_resets_errors():
    bus = EventBus()
    from codeagent.core.contracts.events import AgentEvent

    bus.subscribe(lambda ev: (_ for _ in ()).throw(RuntimeError("炸")))
    bus.emit(AgentEvent("x"))
    assert len(bus.emit_errors) == 1
    bus.clear()
    assert bus.emit_errors == []

