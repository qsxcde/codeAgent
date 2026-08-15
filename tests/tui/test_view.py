"""tests/tui/test_view.py:TuiApp 视图逻辑(注入 stub 后端,不 import textual)。

对应 spec「运行中打断」「空闲退出」「帧率达标」(渲染合并)、「工具调用点击展开」
(点击路由)、「双端底部状态条」(footer 富样式传递)。
"""

import asyncio
from typing import Any

from codeagent.app.tui.components import FooterInfo, ToolCallBlock, rich_to_plain
from codeagent.app.tui.view import TuiApp
from codeagent.core.events import AgentEvent, EventType


class StubBackend:
    """记录渲染/状态/底部状态条/退出文档/点击/补全的假后端(替代 textual,离线断言)。"""

    def __init__(self) -> None:
        self.renders: list[Any] = []
        self.statuses: list[Any] = []
        self.footers: list[Any] = []
        self.submit = None
        self.interrupt = None
        self.resize = None
        self.click = None
        self.input_changed = None
        self.suggestion_nav = None
        self.suggestion_confirm = None
        self.suggestion_lines: list[Any] = []
        self.input_texts: list[str] = []
        self.exited: list[str] | None = None

    def run(self) -> None:  # pragma: no cover - stub
        pass

    def transcript_size(self) -> tuple[int, int]:
        return 60, 10

    def render(self, lines) -> None:
        self.renders.append(list(lines))

    def set_status(self, line) -> None:
        self.statuses.append(line)

    def set_suggestions(self, lines) -> None:
        self.suggestion_lines.append(list(lines) if lines else [])

    def set_input_text(self, text: str) -> None:
        self.input_texts.append(text)

    def on_submit(self, handler) -> None:
        self.submit = handler

    def on_interrupt(self, handler) -> None:
        self.interrupt = handler

    def on_resize(self, handler) -> None:
        self.resize = handler

    def on_click(self, handler) -> None:
        self.click = handler

    def on_input_changed(self, handler) -> None:
        self.input_changed = handler

    def on_suggestion_navigate(self, handler) -> None:
        self.suggestion_nav = handler

    def on_suggestion_confirm(self, handler) -> None:
        self.suggestion_confirm = handler

    def exit_document(self, lines: list[str]) -> None:
        self.exited = list(lines)

    def stop(self) -> None:  # pragma: no cover - stub
        pass


class FakeSession:
    """假会话:订阅回调可按需触发事件;abort 记录调用。"""

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id or f"fake-{len(FakeSession._created)}"
        FakeSession._created.append(self)
        self.subscribers: list[Any] = []
        self.aborted = False

    _created: list["FakeSession"] = []

    def subscribe(self, fn):
        self.subscribers.append(fn)
        return lambda: None

    def run(self, text: str):
        async def _run() -> None:
            self._emit(AgentEvent(EventType.SESSION_STARTED, payload=text))
            self._emit(AgentEvent(EventType.TEXT_DELTA, payload="ok"))
            self._emit(AgentEvent(EventType.TURN_END))

        return _run()

    def abort(self) -> None:
        self.aborted = True

    def _emit(self, event: AgentEvent) -> None:
        for fn in list(self.subscribers):
            fn(event)


class FakeRef:
    """假会话引用(manager.list 返回,供 /sessions 列表展示)。"""

    def __init__(self, session: FakeSession) -> None:
        self.id = session.session_id
        self.title = f"标题-{session.session_id}"


class FakeManager:
    """假会话管理器:单活 current + 订阅转发 + 生命周期(T-44 后 view 只认 manager)。"""

    def __init__(self, session: FakeSession | None = None) -> None:
        self.current = session if session is not None else FakeSession()
        self.sessions = [self.current]
        self.tools: list[Any] = []

    def subscribe(self, fn):
        return self.current.subscribe(fn)

    def create(self):
        session = FakeSession()
        self.sessions.append(session)
        self.current = session
        return session

    def switch(self, session_id: str):
        for session in self.sessions:
            if session.session_id == session_id:
                self.current = session
                return session
        raise ValueError(f"会话不存在: {session_id}")

    def list(self):
        return [FakeRef(s) for s in self.sessions]


def _make_app() -> tuple[TuiApp, StubBackend, FakeManager]:
    backend = StubBackend()
    manager = FakeManager()
    app = TuiApp(manager, backend)
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_resize(app._schedule_render)
    backend.on_click(app._click)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    return app, backend, manager


def test_submit_starts_run_and_renders():
    """提交触发会话运行,事件驱动渲染(对应 spec「对话输入与回复渲染」)。"""
    app, backend, _ = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        backend.submit("你好")
        await asyncio.sleep(0)

    asyncio.run(_run())
    rendered_plain = ["".join(rich_to_plain(lines)) for lines in backend.renders]
    assert any("你好" in text for text in rendered_plain)
    assert "ok" in rendered_plain[-1]
    assert app.model.running is False
    # 状态栏以富样式行传递(design D5)。
    assert backend.statuses and all(isinstance(s, list) for s in backend.statuses)
    assert "ready" not in "".join(s.text for s in backend.statuses[-1])


def test_footer_rich_line_seeded_and_passed():
    """装配数据(model/effort/cwd)经注入进状态栏并以富样式传给后端(design D5)。"""
    backend = StubBackend()
    manager = FakeManager()
    app = TuiApp(
        manager,
        backend,
        footer=FooterInfo(
            model="qwen3.8-max",
            effort="high",
            cwd="/workspace",
        ),
    )
    backend.on_resize(app._schedule_render)

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert backend.statuses, "状态栏未渲染"
    plain = "".join(s.text for s in backend.statuses[-1])
    assert "qwen3.8-max high · /workspace" in plain
    # 状态栏注入模型名与工作目录(回归:此前 status.model 无注入点)
    assert app.model.status.model == "qwen3.8-max"
    assert app.model.status.cwd == "/workspace"


def test_interrupt_running_aborts():
    """运行中 Esc → abort 当前会话(对应 spec「运行中打断」)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    backend.interrupt()
    assert manager.current.aborted is True


def test_interrupt_idle_exits_with_doc():
    """空闲 Esc → 退出并打印完整文档(对应 spec「空闲退出」「退出完整文档」)。"""
    app, backend, manager = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))  # 结束本轮 → 空闲
    backend.interrupt()
    assert backend.exited is not None
    doc = "\n".join(backend.exited)
    assert "hi" in doc
    assert "回复" in doc


def test_run_cancelled_event_returns_idle():
    """RUN_CANCELLED 事件 → 运行态回空闲(对应 spec「运行中打断」)。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    assert app.model.running is True
    app.model.apply(AgentEvent(EventType.RUN_CANCELLED))
    assert app.model.running is False
    assert app.model.activity_visible is False


def test_render_coalescing():
    """N 个增量事件合并成一次渲染(对应 spec「帧率达标」;design D4)。"""
    app, backend, manager = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        before = len(backend.renders)
        # 同一循环迭代内连发多个增量
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="a"))
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="b"))
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="c"))
        await asyncio.sleep(0)
        assert len(backend.renders) - before == 1

    asyncio.run(_run())


def test_activity_timer_runs_only_while_visible():
    """活动提示有独立 UI 定时器，正文到达后立即停止。"""
    app, _, manager = _make_app()

    async def _run() -> None:
        manager.current._emit(AgentEvent(EventType.SESSION_STARTED, payload="x"))
        await asyncio.sleep(0)
        task = app._activity_task
        assert task is not None and not task.done()
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="reply"))
        await asyncio.sleep(0)
        assert app._activity_task is None

    asyncio.run(_run())


def test_click_toggles_tool_expand():
    """点击工具行 → 切换折叠(spec「工具调用点击展开」;design D4)。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    app.model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "read", "args": {"file_path": "a.py"}, "id": "c1"}],
        )
    )
    app.model.transcript.render(60, 10)  # 填充行→块映射
    tool = next(b for b in app.model.transcript.blocks if isinstance(b, ToolCallBlock))
    assert tool.expanded is False
    row = next(i for i in range(10) if app.model.transcript.block_at(i) is tool)
    backend.click(row)
    assert tool.expanded is True
    backend.click(row)
    assert tool.expanded is False


# -- 斜杠命令分派(T-44)------------------------------------------------------


def _rendered_text(app: TuiApp, backend: StubBackend) -> str:
    """取最近一次渲染的纯文本(不触发渲染时手动渲染一次)。"""
    if not backend.renders:
        lines = app.model.render(60, 10)
        return "".join(rich_to_plain(lines))
    return "".join(rich_to_plain(backend.renders[-1]))


def test_submit_command_help_renders_without_run():
    """/help → 渲染命令帮助,不发起对话。"""
    app, backend, manager = _make_app()
    manager.current.run_called = False  # 记录:命令不应触发 run
    backend.submit("/help")
    text = _rendered_text(app, backend)
    assert "可用命令:" in text
    assert "/undo" in text and "未可用" in text


def test_submit_unknown_command_shows_error():
    """未知命令 → 可操作提示,不发送不执行(NFR-U7)。"""
    app, backend, _ = _make_app()
    backend.submit("/foobar")
    text = _rendered_text(app, backend)
    assert "未知命令: /foobar" in text
    assert "会话列表" not in text


def test_submit_double_slash_sends_literal():
    """// 转义 → 按字面量发起对话(去掉一个 /)。"""
    app, backend, manager = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        before = len(manager.current.subscribers)
        backend.submit("//hi")
        await asyncio.sleep(0)

    asyncio.run(_run())
    text = _rendered_text(app, backend)
    assert "/hi" in text  # SESSION_STARTED payload 为转义后的字面量


def test_clear_command_resets_transcript():
    """/clear → 清空聊天区。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="旧内容"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))  # 回空闲,命令才可提交
    assert app.model.transcript.blocks
    backend.submit("/clear")
    assert app.model.transcript.blocks == []
    assert app.model.transcript.follow is True


def test_undo_command_shows_unavailable():
    """/undo → 注册槽位,提示未可用(T-42 前不静默忽略)。"""
    app, backend, _ = _make_app()
    backend.submit("/undo")
    text = _rendered_text(app, backend)
    assert "未可用" in text and "T-42" in text


def test_status_command_shows_session_info():
    """/status → 会话 id / 运行态 / 模型。"""
    app, backend, manager = _make_app()
    app.model.status.model = "deepseek-v4-flash"
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert manager.current.session_id in text
    assert "空闲" in text
    assert "deepseek-v4-flash" in text


def test_tools_command_lists_tool_names():
    """/tools → 列出可用工具。"""
    app, backend, manager = _make_app()
    manager.tools = [type("T", (), {"name": "bash"})(), type("T", (), {"name": "read"})()]
    backend.submit("/tools")
    text = _rendered_text(app, backend)
    assert "bash" in text and "read" in text


def test_sessions_list_switch_and_new():
    """/sessions:列表 / <id> 切换 / new 新建。"""
    app, backend, manager = _make_app()
    first = manager.current

    backend.submit("/sessions")
    text = _rendered_text(app, backend)
    assert "会话列表:" in text and first.session_id in text

    backend.submit("/sessions new")
    assert manager.current is not first

    backend.submit(f"/sessions {first.session_id}")
    assert manager.current is first
    text = _rendered_text(app, backend)
    assert "已切换到会话" in text

    backend.submit("/sessions ghost")
    text = _rendered_text(app, backend)
    assert "会话不存在" in text


def test_config_commands_use_rebuild_ports():
    """/provider /model /effort 经注入回调热切换,状态栏同步更新。"""
    calls: list[tuple] = []
    backend = StubBackend()
    manager = FakeManager()

    def rebuild(provider, model, effort):
        calls.append((provider, model, effort))
        return "m2", "high"

    app = TuiApp(manager, backend, rebuild_ports=rebuild)
    backend.on_submit(app._submit)

    backend.submit("/provider deepseek")
    assert calls[-1] == ("deepseek", None, None)
    assert app.model.status.model == "m2" and app.model.status.effort == "high"

    backend.submit("/model deepseek-v4:high")
    assert calls[-1] == (None, "deepseek-v4:high", None)

    backend.submit("/effort low")
    assert calls[-1] == (None, None, "low")


def test_config_command_without_args_shows_usage():
    """/provider 无参数 → 用法提示,不触发热切换。"""
    calls: list = []
    backend = StubBackend()
    app = TuiApp(
        FakeManager(),
        backend,
        rebuild_ports=lambda p, m, e: (calls.append(1), ("", ""))[1],
    )
    backend.on_submit(app._submit)
    backend.submit("/provider")
    text = _rendered_text(app, backend)
    assert "/provider <name>" in text
    assert calls == []


def test_config_command_invalid_provider_shows_error():
    """/provider 未知值 → 回调 ValueError 就地提示(NFR-U7 容错)。"""
    backend = StubBackend()

    def rebuild(provider, model, effort):
        raise ValueError("未知的 provider: 'nope'")

    app = TuiApp(FakeManager(), backend, rebuild_ports=rebuild)
    backend.on_submit(app._submit)
    backend.submit("/provider nope")
    text = _rendered_text(app, backend)
    assert "未知的 provider" in text


# -- 模糊补全与选择器(T-45)---------------------------------------------------


def test_input_changed_shows_command_suggestions():
    """/ + 前缀 → 浮层展示模糊匹配的命令建议。"""
    app, backend, _ = _make_app()
    backend.input_changed("/st")
    assert app._suggestions  # 命中 status/sessions 等
    assert app._suggestions[0] == "status"  # 精确前缀优先
    # 浮层渲染为样式标签行
    lines = backend.suggestion_lines[-1]
    assert lines and "/status" in lines[0][1].text


def test_input_changed_plain_text_hides_suggestions():
    """普通文本输入 → 无建议、浮层隐藏。"""
    app, backend, _ = _make_app()
    backend.input_changed("你好")
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []


def test_suggestion_navigate_cycles_and_confirm_fills():
    """↑/↓ 循环选择,确认后填入输入框并收起浮层。"""
    app, backend, _ = _make_app()
    backend.input_changed("/s")
    total = len(app._suggestions)
    backend.suggestion_nav(1)
    assert app._suggestion_index == 1
    backend.suggestion_nav(-1)
    assert app._suggestion_index == 0
    backend.suggestion_nav(-1)  # 循环到头
    assert app._suggestion_index == total - 1
    selected = app._suggestions[total - 1]
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == f"/{selected}"
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []


def test_provider_selector_candidates_injected():
    """选择器候选经组合根注入:/provider 空格后按候选模糊匹配。"""
    app, backend, _ = _make_app()
    app._candidates = {"provider": ["deepseek", "openai", "qwen"], "model": [], "effort": []}
    backend.input_changed("/provider deep")
    names = list(app._suggestions)
    assert names == ["deepseek"]
    backend.input_changed("/provider o")
    assert app._suggestions[0] == "openai"
    # 非选择器命令不触发候选
    backend.input_changed("/clear x")
    assert app._suggestions == []


# -- 补全/提交缺陷回归(fix-tui-command-completion)----------------------------


def test_confirm_suppresses_async_repopulate():
    """(回归:D1)确认填入后,set_input_text 引发的异步变更通知不重弹浮层。

    早期缺陷:confirm 同步清理浮层,但异步 Changed 事件重算建议使浮层复活,
    Enter 永远被消费为确认,命令无法提交。正确行为:该次通知被抑制,
    浮层保持收起;后续真实编辑恢复正常建议计算。
    """
    app, backend, _ = _make_app()
    backend.input_changed("/tools")
    assert app._suggestions == ["tools"]
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/tools"
    # 模拟 textual 异步投递的 Changed 通知(内容 = 填入后的文本)。
    backend.input_changed("/tools")
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []
    # 标志只消费一次:继续编辑恢复正常建议计算。
    backend.input_changed("/to")
    assert app._suggestions == ["tools"]


def test_submit_after_confirm_executes_command():
    """(回归:D1)确认填入后直接提交,命令被执行而非再次确认。"""
    app, backend, _ = _make_app()
    backend.input_changed("/tools")
    backend.suggestion_confirm()
    backend.input_changed("/tools")  # 异步变更通知(被抑制)
    backend.submit("/tools")
    assert "可用工具" in _rendered_text(app, backend)


def test_bare_slash_shows_all_commands():
    """(回归:D2)单独输入 / 展示全量命令建议(注册表原序)。"""
    from codeagent.app.tui.commands import default_registry

    app, backend, _ = _make_app()
    backend.input_changed("/")
    assert app._suggestions == list(default_registry())


def test_selector_empty_arg_shows_all_candidates():
    """(回归:D4)/model 等选择器空参(仅尾随空格)展示全量候选。"""
    app, backend, _ = _make_app()
    app._candidates = {
        "provider": ["deepseek", "openai"],
        "model": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "effort": ["low", "medium", "high"],
    }
    backend.input_changed("/model ")
    assert app._suggestions == ["deepseek-v4-pro", "deepseek-v4-flash"]
    backend.input_changed("/provider ")
    assert app._suggestions == ["deepseek", "openai"]
    backend.input_changed("/effort ")
    assert app._suggestions == ["low", "medium", "high"]
    # 无空格仍是命令名补全,不进选择器。
    backend.input_changed("/model")
    assert app._suggestions == ["model"]
