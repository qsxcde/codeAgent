"""会话层测试:事件订阅、会话维度 thread 累积、run 不返回值。"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode

from codeagent.ai.providers.fake import FakeClient
from codeagent.core import AgentPorts, EventType, build_graph
from codeagent.session import AgentSession, EventBus
from codeagent.tools.registry import make_tools


def _session(model: FakeClient) -> AgentSession:
    from codeagent.ai.bridge.langchain import to_langchain_runnable

    tools = make_tools()
    bound = to_langchain_runnable(model.bind_tools(tools))
    ports = AgentPorts(
        bound_model=bound,
        tool_executor=ToolNode(tools),
        checkpointer=InMemorySaver(),
    )
    return AgentSession(build_graph(ports), EventBus())


def test_run_returns_none_and_emits_events():
    sess = _session(FakeClient(response="OK"))
    seen: list[str] = []
    sess.subscribe(lambda e: seen.append(e.type))

    asyncio.run(sess.run("你好"))
    assert EventType.SESSION_STARTED in seen
    assert EventType.TEXT_DELTA in seen
    assert EventType.TURN_END in seen


def test_run_recursion_limit_override_used_in_config():
    """run 传 recursion_limit 时 config 生效;缺省用构造配置(回归:P2-15)。"""
    captured: list[dict] = []

    class StubGraph:
        async def astream(self, initial, config=None, **kwargs):
            captured.append(config)
            return
            yield  # pragma: no cover - 使本函数成为异步生成器

    sess = AgentSession(StubGraph(), EventBus(), recursion_limit=50)

    # 缺省用构造值
    asyncio.run(sess.run("默认"))
    assert captured[-1]["recursion_limit"] == 50

    # 单轮覆盖
    asyncio.run(sess.run("覆盖", recursion_limit=100))
    assert captured[-1]["recursion_limit"] == 100

    # 构造时指定
    sess2 = AgentSession(StubGraph(), EventBus(), recursion_limit=75)
    asyncio.run(sess2.run("构造指定"))
    assert captured[-1]["recursion_limit"] == 75


def test_final_reply_streamed_via_text_delta_no_duplicate():
    """最终回复经 TEXT_DELTA 流式交付,不再重复发 AGENT_MESSAGE(回归:P2-1 + 去重)。

    早期缺陷:stream_mode 同时产出 messages(整段)+ updates(整段),TEXT_DELTA
    与 AGENT_MESSAGE 各发一次同文本。现在文本以 TEXT_DELTA 交付,AGENT_MESSAGE 抑制。
    """
    sess = _session(FakeClient(response="最终回复"))
    seen: list[tuple[str, object]] = []
    sess.subscribe(lambda e: seen.append((e.type, e.payload)))

    asyncio.run(sess.run("你好"))

    text_deltas = [p for t, p in seen if t == EventType.TEXT_DELTA]
    assert text_deltas, f"未收到 TEXT_DELTA,事件序列: {[t for t, _ in seen]}"
    assert text_deltas[-1] == "最终回复"
    agent_msgs = [p for t, p in seen if t == EventType.AGENT_MESSAGE]
    assert not agent_msgs, "TEXT_DELTA 已流式产出后不应重复发 AGENT_MESSAGE(去重)"


def test_tool_call_aimessage_does_not_emit_agent_message(tmp_path):
    """带 tool_calls 的 AIMessage 走 TOOL_CALL 分支,不发 AGENT_MESSAGE(回归:P2-1)。"""
    target = tmp_path / "c.txt"
    target.write_text("数据")
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "read", "args": {"file_path": str(target)}, "id": "c1", "type": "tool_call"}
                ],
            },
            {"content": "完成"},
        ]
    )
    sess = _session(model)
    seen: list[str] = []
    sess.subscribe(lambda e: seen.append(e.type))

    asyncio.run(sess.run("读"))
    assert EventType.TOOL_CALL in seen
    # 最终回复 "完成" 经 TEXT_DELTA 流式交付,不重复发 AGENT_MESSAGE(去重)
    assert EventType.AGENT_MESSAGE not in seen
    assert EventType.TEXT_DELTA in seen


def test_event_bus_multiple_subscribers():
    from codeagent.core import AgentEvent

    bus = EventBus()
    got1, got2 = [], []
    bus.subscribe(lambda e: got1.append(e.type))
    bus.subscribe(lambda e: got2.append(e.type))
    bus.emit(AgentEvent(EventType.TURN_END))
    assert got1 == [EventType.TURN_END]
    assert got2 == [EventType.TURN_END]


def test_event_bus_unsubscribe():
    from codeagent.core import AgentEvent

    bus = EventBus()
    got = []
    unsub = bus.subscribe(lambda e: got.append(e.type))
    bus.emit(AgentEvent(EventType.SESSION_STARTED))
    unsub()
    bus.emit(AgentEvent(EventType.TURN_END))
    assert got == [EventType.SESSION_STARTED]


def test_event_bus_subscriber_exception_does_not_break_others():
    """订阅方抛异常不中断后续订阅方,且异常被记录(回归:P2-17)。"""
    from codeagent.core import AgentEvent

    bus = EventBus()
    got: list[str] = []

    def boom(_event):
        raise RuntimeError("订阅方炸了")

    bus.subscribe(boom)
    bus.subscribe(lambda e: got.append(e.type))

    bus.emit(AgentEvent(EventType.TURN_END))

    assert got == [EventType.TURN_END]
    assert len(bus.emit_errors) == 1
    assert bus.emit_errors[0][1].args[0] == "订阅方炸了"
    assert bus.emit_errors[0][0].type == EventType.TURN_END


def test_event_bus_clear_resets_errors():
    from codeagent.core import AgentEvent

    bus = EventBus()
    bus.subscribe(lambda _e: (_ for _ in ()).throw(RuntimeError("x")))
    bus.emit(AgentEvent(EventType.TURN_END))
    assert len(bus.emit_errors) == 1
    bus.clear()
    assert bus.emit_errors == []
    assert len(bus) == 0


def test_session_thread_accumulates_context():
    sess = _session(FakeClient(response="收到"))
    events: list[str] = []
    sess.subscribe(lambda e: events.append(e.type))

    asyncio.run(sess.run("第一轮"))
    asyncio.run(sess.run("第二轮"))

    # 第二轮 run 后,同一 thread 的状态应累积两条 HumanMessage
    graph = sess._graph

    async def _state():
        return await graph.aget_state(
            {"configurable": {"thread_id": sess._thread_id}}
        )

    state = asyncio.run(_state())
    humans = [
        m.content
        for m in state.values["messages"]
        if type(m).__name__ == "HumanMessage"
    ]
    assert humans == ["第一轮", "第二轮"]


def test_tool_events_emitted(tmp_path):
    target = tmp_path / "b.txt"
    target.write_text("数据")
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "read", "args": {"file_path": str(target)}, "id": "c1", "type": "tool_call"}
                ],
            },
            {"content": "完成"},
        ]
    )
    sess = _session(model)
    seen = []
    sess.subscribe(seen.append)

    asyncio.run(sess.run("读"))
    assert EventType.TOOL_CALL in [event.type for event in seen]
    result = next(event for event in seen if event.type == EventType.TOOL_RESULT)
    assert result.metadata["tool_call_id"] == "c1"
    assert result.metadata["tool_name"] == "read"
    assert EventType.TEXT_DELTA in [event.type for event in seen]
    assert EventType.TURN_END in [event.type for event in seen]


def test_tool_error_flagged_in_metadata(tmp_path):
    """工具执行失败时 TOOL_RESULT 事件 metadata 携带 error 标志(回归)。

    早期缺陷:core 节点层生成的错误 ToolMessage 无错误标记,session 不透传,
    TUI 无法区分成功/失败,工具失败永远显示成功图标。
    """
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "name": "read",
                        "args": {"file_path": str(tmp_path / "missing.txt")},
                        "id": "c1",
                        "type": "tool_call",
                    }
                ],
            },
            {"content": "完成"},
        ]
    )
    sess = _session(model)
    seen = []
    sess.subscribe(seen.append)

    asyncio.run(sess.run("读"))
    result = next(event for event in seen if event.type == EventType.TOOL_RESULT)
    assert result.metadata["error"] is True
    assert "[工具执行出错]" in str(result.payload)


def test_run_emits_error_event_on_graph_failure():
    """图运行异常时,run 发出 ERROR 事件且仍发 TURN_END。"""

    class BoomModel(FakeClient):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("图炸了")

    sess = _session(BoomModel(response="x"))
    seen: list[tuple[str, str | None]] = []
    sess.subscribe(lambda e: seen.append((e.type, e.payload)))

    asyncio.run(sess.run("触发"))

    types = [t for t, _ in seen]
    assert EventType.ERROR in types
    assert EventType.TURN_END in types
    error_payload = next(p for t, p in seen if t == EventType.ERROR)
    assert error_payload and "图炸了" in error_payload


def test_thinking_delta_emitted():
    """推理模型的思考过程以 THINKING_DELTA 透传,与正文 TEXT_DELTA 分开。"""
    sess = _session(FakeClient(thinking="先分析再回答", response="回复内容"))
    seen: list[tuple[str, object]] = []
    sess.subscribe(lambda e: seen.append((e.type, e.payload)))

    asyncio.run(sess.run("你好"))

    thinking = [p for t, p in seen if t == EventType.THINKING_DELTA]
    assert thinking, f"未收到 THINKING_DELTA,事件序列: {[t for t, _ in seen]}"
    assert "先分析再回答" in "".join(str(p) for p in thinking)
    text = [p for t, p in seen if t == EventType.TEXT_DELTA]
    assert text and "回复内容" in "".join(str(p) for p in text)


def test_error_rolls_back_unfinished_turn():
    """图失败后,本轮未完成 turn 的消息被回滚,不污染后续上下文。"""

    class BoomModel(FakeClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._calls = 0

        def _generate(self, messages, **kwargs):
            self._calls += 1
            if self._calls == 2:
                raise RuntimeError("图炸了")
            return super()._generate(messages)

    sess = _session(BoomModel(response="正常回复"))
    asyncio.run(sess.run("第一轮"))
    asyncio.run(sess.run("第二轮"))  # 抛错 → ERROR + 回滚

    async def _state():
        return await sess._graph.aget_state(
            {"configurable": {"thread_id": sess._thread_id}}
        )

    state = asyncio.run(_state())
    contents = [m.content for m in state.values["messages"]]
    assert "第一轮" in contents
    assert "第二轮" not in contents, "未完成 turn 的用户消息应被回滚"


def test_recursion_error_friendly_message_and_rollback():
    """递归超限:ERROR payload 转友好提示,且本轮消息被回滚。"""
    from codeagent.ai.protocol.messages import ChatResponse, ToolCall

    class LoopModel(FakeClient):
        def _generate(self, messages, **kwargs):
            # 永远请求调用工具 → 循环直到 recursion_limit 触底
            return ChatResponse(
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="read", arguments='{"file_path": "nope"}')
                ],
                finish_reason="tool_calls",
                model="fake-model",
            )

    sess = _session(LoopModel(response="x"))
    seen: list[tuple[str, str | None]] = []
    sess.subscribe(lambda e: seen.append((e.type, e.payload)))

    asyncio.run(sess.run("循环", recursion_limit=4))

    error_payload = next(p for t, p in seen if t == EventType.ERROR)
    assert error_payload and "模型连续调用工具次数过多" in error_payload

    async def _state():
        return await sess._graph.aget_state(
            {"configurable": {"thread_id": sess._thread_id}}
        )

    state = asyncio.run(_state())
    contents = [m.content for m in state.values["messages"]]
    assert "循环" not in contents, "递归超限后的消息也应被回滚"


def test_friendly_error_classifies_http_and_network_errors():
    """HTTP 状态码 / 超时 / 连接错误转中文友好提示;其它异常原样。"""
    import httpx

    def _http(status: int) -> httpx.HTTPStatusError:
        req = httpx.Request("POST", "https://api.example.com/chat/completions")
        resp = httpx.Response(status, request=req)
        return httpx.HTTPStatusError("错误", request=req, response=resp)

    assert "认证失败" in AgentSession._friendly_error(_http(401))
    assert "认证失败" in AgentSession._friendly_error(_http(403))
    assert "模型或端点不存在" in AgentSession._friendly_error(_http(404))
    assert "请求过于频繁" in AgentSession._friendly_error(_http(429))
    assert "HTTP 500" in AgentSession._friendly_error(_http(500))
    assert "请求超时" in AgentSession._friendly_error(httpx.ReadTimeout("慢"))
    assert "无法连接" in AgentSession._friendly_error(httpx.ConnectError("拒绝连接"))
    assert AgentSession._friendly_error(RuntimeError("原始错误")) == "原始错误"


def test_run_sync_without_loop_completes():
    """无运行中事件循环时,run_sync 正常阻塞完成(回归:P2-7)。"""
    sess = _session(FakeClient(response="同步回复"))
    seen: list[str] = []
    sess.subscribe(lambda e: seen.append(e.type))

    sess.run_sync("你好")

    assert EventType.SESSION_STARTED in seen
    assert EventType.TURN_END in seen


def test_run_sync_inside_running_loop_does_not_raise():
    """已有运行中事件循环的线程调用 run_sync 不抛 RuntimeError(回归:P2-7)。"""

    async def _main() -> list[str]:
        sess = _session(FakeClient(response="嵌套回复"))
        seen: list[str] = []
        sess.subscribe(lambda e: seen.append(e.type))
        # 在运行中 loop 内调用同步入口,走新线程路径
        sess.run_sync("你好")
        return seen

    seen = asyncio.run(_main())
    assert EventType.SESSION_STARTED in seen
    assert EventType.TURN_END in seen


def test_run_sync_graph_error_becomes_error_event():
    """run_sync 下与 run 语义一致:图异常转成 ERROR 事件而非向上抛。"""

    class BoomModel(FakeClient):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("同步图炸了")

    sess = _session(BoomModel(response="x"))
    seen: list[tuple[str, str | None]] = []
    sess.subscribe(lambda e: seen.append((e.type, e.payload)))

    sess.run_sync("触发")

    types = [t for t, _ in seen]
    assert EventType.ERROR in types
    assert EventType.TURN_END in types
    error_payload = next(p for t, p in seen if t == EventType.ERROR)
    assert error_payload and "同步图炸了" in error_payload


def test_abort_cancels_running_run_and_emits_run_cancelled():
    """run() 进行中被 abort → RUN_CANCELLED 广播,run 以 CancelledError 结束。"""
    events: list[str] = []
    calls: list[str] = []

    class SlowGraph:
        async def astream(self, initial, config=None, stream_mode=None):
            for _ in range(10):
                await asyncio.sleep(0.01)
                yield ("updates", {"agent": {"messages": []}})

        async def aget_state(self, config=None):
            return type("S", (), {"values": {"messages": []}})()

        async def aupdate_state(self, config, values):  # pragma: no cover
            pass

    sess = AgentSession(SlowGraph(), None)
    # 用真实 EventBus 替换 None,便于订阅
    from codeagent.session.bus import EventBus

    sess._bus = EventBus()
    sess.subscribe(lambda ev: events.append(ev.type))

    async def scenario():
        task = asyncio.create_task(sess.run("hi"))
        await asyncio.sleep(0.03)  # 等 astream 开始
        sess.abort()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert EventType.RUN_CANCELLED in events
    assert EventType.TURN_END in events  # finally 仍发 turn_end


def test_usage_event_emitted_from_aimessage_usage_metadata():
    """AIMessage 带 usage_metadata → USAGE 事件透传 input/output/reasoning。"""
    events: list[str] = []
    from codeagent.session.bus import EventBus

    class SimpleGraph:
        async def astream(self, initial, config=None, stream_mode=None):
            msg = AIMessage(
                content="回答",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "total_tokens": 30,
                    "output_token_details": {"reasoning": 7},
                },
            )
            yield ("updates", {"agent": {"messages": [msg]}})

        async def aget_state(self, config=None):
            return type("S", (), {"values": {"messages": []}})()

        async def aupdate_state(self, config, values):  # pragma: no cover
            pass

    sess = AgentSession(SimpleGraph(), EventBus())
    payloads: list[dict] = []
    sess.subscribe(lambda ev: payloads.append(ev.payload) if ev.type == EventType.USAGE else None)
    asyncio.run(sess.run("hi"))
    assert payloads
    assert payloads[0]["input_tokens"] == 10
    assert payloads[0]["output_tokens"] == 20
    assert payloads[0]["reasoning_tokens"] == 7
