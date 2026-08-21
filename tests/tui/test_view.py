"""tests/tui/test_view.py:TuiApp 视图逻辑(注入 stub 后端,不 import textual)。

对应 spec「运行中打断」「空闲退出」「帧率达标」(渲染合并)、「工具调用点击展开」
(点击路由)、「双端底部状态条」(footer 富样式传递)。
"""

import asyncio
from types import SimpleNamespace
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
        self.quit = None
        self.resize = None
        self.click = None
        self.input_changed = None
        self.suggestion_nav = None
        self.suggestion_confirm = None
        self.scroll = None
        self.confirmation_response = None
        self.confirmation_lines: list[Any] = []
        self.suggestion_lines: list[Any] = []
        self.input_texts: list[str] = []
        self.mask_calls: list[bool] = []
        self.placeholders: list[str] = []
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

    def set_input_mask(self, masked: bool) -> None:
        self.mask_calls.append(masked)

    def set_input_placeholder(self, text: str) -> None:
        self.placeholders.append(text)

    def on_submit(self, handler) -> None:
        self.submit = handler

    def on_interrupt(self, handler) -> None:
        self.interrupt = handler

    def on_quit(self, handler) -> None:
        self.quit = handler

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

    def on_scroll(self, handler) -> None:
        self.scroll = handler

    def set_confirmation(self, lines) -> None:
        self.confirmation_lines.append(list(lines) if lines else [])

    def on_confirmation_response(self, handler) -> None:
        self.confirmation_response = handler

    def exit_document(self, lines: list[str]) -> None:
        self.exited = list(lines)

    def stop(self) -> None:  # pragma: no cover - stub
        pass


class FakeSession:
    """假会话:订阅回调可按需触发事件;abort 记录调用;run 记录文本。"""

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id or f"fake-{len(FakeSession._created)}"
        FakeSession._created.append(self)
        self.subscribers: list[Any] = []
        self.aborted = False
        self.approvals: list[tuple[str, bool]] = []
        self.run_texts: list[str] = []

    _created: list["FakeSession"] = []

    def subscribe(self, fn):
        self.subscribers.append(fn)
        return lambda: None

    def run(self, text: str):
        self.run_texts.append(text)

        async def _run() -> None:
            self._emit(AgentEvent(EventType.SESSION_STARTED, payload=text))
            self._emit(AgentEvent(EventType.TEXT_DELTA, payload="ok"))
            self._emit(AgentEvent(EventType.TURN_END))

        return _run()

    def abort(self) -> None:
        self.aborted = True

    def respond_approval(self, request_id: str, approved: bool) -> None:
        self.approvals.append((request_id, approved))

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
        self.fork_calls: list[tuple[str, str | None]] = []

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

    def fork(self, session_id: str, message_id: str | None = None):
        self.fork_calls.append((session_id, message_id))
        session = FakeSession()
        self.sessions.append(session)
        self.current = session
        return session


def _make_app() -> tuple[TuiApp, StubBackend, FakeManager]:
    backend = StubBackend()
    manager = FakeManager()
    app = TuiApp(manager, backend)
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_quit(app._quit)
    backend.on_resize(app._schedule_render)
    backend.on_click(app._click)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    backend.on_scroll(app._on_scroll)
    backend.on_confirmation_response(app._on_confirmation_response)
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


def test_interrupt_idle_prompts_quit_hint():
    """空闲 Esc → 提示「按 Ctrl+C 退出」,不再直接退出(收尾补丁:退出键位拆分)。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))  # 结束本轮 → 空闲
    backend.interrupt()
    assert backend.exited is None  # 不退出
    text = _rendered_text(app, backend)
    assert "Ctrl+C" in text


def test_quit_idle_exits_with_doc():
    """空闲 Ctrl+C → 退出并打印完整文档(对应 spec「退出完整文档」)。"""
    app, backend, manager = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))
    backend.quit()
    assert backend.exited is not None
    doc = "\n".join(backend.exited)
    assert "hi" in doc
    assert "回复" in doc


def test_quit_running_aborts_then_exits():
    """运行中 Ctrl+C → 先中止当前轮(abort),再退出(未完成轮次不落盘)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    backend.quit()
    assert manager.current.aborted is True
    assert backend.exited is not None


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


# -- 滚动交互(T-47,specc「alt 屏渲染与滚动」)---------------------------------


def _fill_transcript(app: TuiApp) -> None:
    """填充远超一屏的内容(40 × 40 字符 ≈ 28 行 > 视口 10 行),使滚动语义可被观察。"""
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    for _ in range(40):
        app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="x" * 40))
    app.model.apply(AgentEvent(EventType.TURN_END))
    app.model.transcript.render(60, 10)


def test_wheel_scroll_up_unfollows_and_new_output_does_not_jump():
    """滚轮上滚 → 解除跟随;新输出不强制跳回底部(spec「上滚浏览历史」)。"""
    app, backend, manager = _make_app()
    _fill_transcript(app)
    assert app.model.transcript.follow is True
    backend.scroll(3)  # 滚轮一格(上滚)
    assert app.model.transcript.follow is False
    first_line = app.model.transcript.render(60, 10)[0][0].text
    # 上滚后新正文到达:不跳回底部,视口内容不变
    manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="new "))
    manager.current._emit(AgentEvent(EventType.TURN_END))
    assert app.model.transcript.follow is False
    assert app.model.transcript.render(60, 10)[0][0].text == first_line


def test_scroll_back_to_bottom_restores_follow():
    """滚回底部 → 恢复跟随(spec「回到底部恢复跟随」)。"""
    app, backend, _ = _make_app()
    _fill_transcript(app)
    backend.scroll(3)
    assert app.model.transcript.follow is False
    backend.scroll(-1000)  # 持续下滚越过底部
    app.model.transcript.render(60, 10)
    assert app.model.transcript.follow is True


def test_keyboard_page_up_down_dispatches_scroll():
    """PageUp/PageDown → 一页行数增量,上翻解除跟随、下翻回底恢复(spec「键盘滚动」)。"""
    app, backend, _ = _make_app()
    _fill_transcript(app)
    backend.scroll(9)  # PageUp 一页(视口高 10 - 1):解除跟随
    assert app.model.transcript.follow is False
    backend.scroll(9)  # PageUp 再一页:位置 20 → 2
    backend.scroll(-9)  # PageDown 一页:2 → 11,未到底,仍不跟随
    assert app.model.transcript.follow is False
    backend.scroll(-1000)  # PageDown 越过底部
    app.model.transcript.render(60, 10)
    assert app.model.transcript.follow is True


def test_start_registers_scroll_handler():
    """start() 注册 on_scroll 回调(端口接线;design T-47)。"""
    backend = StubBackend()
    app = TuiApp(FakeManager(), backend)
    app.start()  # StubBackend.run 为 no-op,只测注册
    assert backend.scroll is not None
    assert backend.scroll(5) is None  # 处理器可调用且不抛错


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
    # 无界高度渲染全文(命令表变长后视口会裁剪行首,不影响命令语义)。
    text = "\n".join(app.model.transcript.all_lines(240))
    assert "/fork" in text and "/compact" in text
    assert "/skills" in text


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


def test_fork_command_dispatches_and_feedback():
    """/fork → manager.fork(缺省最近用户消息),反馈含新会话 id 与原会话保留提示。"""
    app, backend, manager = _make_app()
    current_id = manager.current.session_id
    backend.submit("/fork")
    assert manager.fork_calls == [(current_id, None)]
    text = _rendered_text(app, backend)
    assert "已分叉会话" in text
    assert "重新开始" in text  # 反馈含分叉点语义(换行后短语仍可断言)
    assert "文件保持当前状态" in text


def test_fork_command_with_message_id():
    """/fork <message-id> → 显式分叉点传给 manager。"""
    app, backend, manager = _make_app()
    before_id = manager.current.session_id
    backend.submit("/fork msg-123")
    assert manager.fork_calls == [(before_id, "msg-123")]


def test_fork_command_error_shown_inline():
    """/fork 非法分叉点 → ValueError 就地提示,不崩溃。"""
    backend = StubBackend()
    manager = FakeManager()

    class BoomManager(FakeManager):
        def fork(self, session_id, message_id=None):
            raise ValueError("分叉点必须是 user 消息: msg-x")

    app = TuiApp(BoomManager(), backend)
    backend.on_submit(app._submit)
    backend.submit("/fork msg-x")
    text = _rendered_text(app, backend)
    assert "分叉点必须是 user 消息" in text


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
    app._candidates = {"provider": ["deepseek", "openai", "qwen"], "model": {}, "effort": []}
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
    assert app._suggestions == list(default_registry())[:9]  # 浮层上限 _MAX_SUGGESTIONS


def test_selector_empty_arg_shows_all_candidates():
    """(回归:D4)/model 等选择器空参(仅尾随空格)展示全量候选。"""
    app, backend, _ = _make_app()
    app._candidates = {
        "provider": ["deepseek", "openai"],
        "model": {"deepseek": ["deepseek-v4-pro", "deepseek-v4-flash"]},
        "effort": ["low", "medium", "high"],
    }
    app._provider = "deepseek"
    backend.input_changed("/model ")
    assert app._suggestions == ["deepseek-v4-pro", "deepseek-v4-flash"]
    backend.input_changed("/provider ")
    assert app._suggestions == ["deepseek", "openai"]
    backend.input_changed("/effort ")
    assert app._suggestions == ["low", "medium", "high"]
    # 无空格仍是命令名补全,不进选择器。
    backend.input_changed("/model")
    assert app._suggestions == ["model"]


# -- 确认交互(security-permissions)-------------------------------------------


def _confirm_event(**overrides) -> AgentEvent:
    """构造确认请求事件(默认 payload 含 request_id/tool_call_id/summary/reason)。"""
    payload = {
        "request_id": "cf-r1",
        "tool_call_id": "c1",
        "tool": "bash",
        "summary": "git push origin main",
        "reason": "推送远程分支",
    }
    payload.update(overrides)
    return AgentEvent(EventType.CONFIRMATION_REQUESTED, payload=payload)


def test_confirmation_event_shows_bar():
    """确认请求事件 → 确认条渲染(工具/摘要/原因可见),后端激活。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    manager = app._manager
    manager.current._emit(_confirm_event())
    assert backend.confirmation_lines[-1], "确认条未显示"
    plain = "".join(s.text for line in backend.confirmation_lines[-1] for s in line)
    assert "需要确认" in plain
    assert "git push origin main" in plain
    assert "推送远程分支" in plain
    assert app._pending_confirmation is not None


def test_confirmation_yes_forwards_approval():
    """y 响应 → 会话 respond_approval(request_id, True),确认条收起。"""
    app, backend, manager = _make_app()
    manager.current._emit(_confirm_event())
    backend.confirmation_response(True)
    assert manager.current.approvals == [("cf-r1", True)]
    assert backend.confirmation_lines[-1] == []
    assert app._pending_confirmation is None


def test_confirmation_no_forwards_rejection():
    """n 响应 → 会话 respond_approval(request_id, False),确认条收起。"""
    app, backend, manager = _make_app()
    manager.current._emit(_confirm_event())
    backend.confirmation_response(False)
    assert manager.current.approvals == [("cf-r1", False)]


def test_esc_while_confirmation_aborts_run():
    """确认激活时 Esc → 中断当前运行(拒绝并中止语义;RUN_CANCELLED 后条收起)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    manager.current._emit(_confirm_event())
    backend.interrupt()
    assert manager.current.aborted is True
    manager.current._emit(AgentEvent(EventType.RUN_CANCELLED))
    assert app._pending_confirmation is None
    assert backend.confirmation_lines[-1] == []


def test_terminal_event_clears_confirmation_bar():
    """终态事件(TURN_END)→ 确认条收起(不再悬挂)。"""
    app, backend, manager = _make_app()
    manager.current._emit(_confirm_event())
    manager.current._emit(AgentEvent(EventType.TURN_END))
    assert app._pending_confirmation is None
    assert backend.confirmation_lines[-1] == []


def test_rejected_tool_result_marks_block():
    """拒绝的 TOOL_RESULT(rejected 元数据)→ 工具块进入拒绝态(图标 ✗)。"""
    app, _, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    app.model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "bash", "args": {"command": "git push"}, "id": "c1"}],
        )
    )
    app.model.apply(
        AgentEvent(
            EventType.TOOL_RESULT,
            payload="[工具执行被拒绝] 用户拒绝执行: 推送远程分支",
            metadata={"tool_call_id": "c1", "error": True, "rejected": True},
        )
    )
    block = next(b for b in app.model.transcript.blocks if isinstance(b, ToolCallBlock))
    assert block.rejected is True and block.status == "error"
    header = block.render(60)[0]
    assert header[2].text == "✗"
    assert "Rejected bash" in "".join(s.text for s in header)


def test_start_registers_confirmation_handler():
    """start() 注册确认响应回调(端口接线)。"""
    backend = StubBackend()
    app = TuiApp(FakeManager(), backend)
    app.start()
    assert backend.confirmation_response is not None
    backend.confirmation_response(True)  # 无 pending 时安全忽略


# -- 上下文文件来源展示(agents-md-hierarchy)----------------------------------


def test_status_shows_agents_sources_when_injected():
    """/status:注入来源列表 → 展示上下文文件(加载结果可见)。"""
    backend = StubBackend()
    app = TuiApp(
        FakeManager(),
        backend,
        agents_sources=["/global/AGENTS.md", "/proj/AGENTS.md"],
    )
    backend.on_submit(app._submit)
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "上下文文件:" in text
    assert "/global/AGENTS.md" in text
    assert "/proj/AGENTS.md" in text


def test_status_without_sources_shows_none():
    """/status:未注入来源 → 明确显示 (无)。"""
    app, backend, _ = _make_app()
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "上下文文件: (无)" in text


# -- 压缩命令(session-compaction)---------------------------------------------


def test_compact_command_dispatches_and_feedback():
    """/compact → 会话 compact 异步执行,完成后反馈压缩结果。"""
    backend = StubBackend()

    class CompactSession(FakeSession):
        async def compact(self):
            return True

    class CompactManager(FakeManager):
        def __init__(self):
            super().__init__(session=CompactSession())

    app = TuiApp(CompactManager(), backend)
    backend.on_submit(app._submit)
    backend.on_resize(app._schedule_render)

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        backend.submit("/compact")
        for _ in range(20):  # 等异步 compact 完成并渲染
            await asyncio.sleep(0.01)
            text = "".join(rich_to_plain(backend.renders[-1]))
            if "已压缩" in text:
                return
        raise AssertionError("未收到压缩完成反馈")

    asyncio.run(_run())


def test_compact_command_unavailable_inline():
    """/compact 会话不支持压缩(无 compact 方法)→ 就地提示。"""
    app, backend, _ = _make_app()
    backend.submit("/compact")
    text = _rendered_text(app, backend)
    assert "不可用" in text


# -- 内联选择(/provider /model /effort picker)---------------------------------


def _make_picker_app() -> tuple[TuiApp, StubBackend, list]:
    """内联选择测试夹具:model 候选按 provider 分表;footer 注入 provider 当前值。"""
    calls: list[tuple] = []

    def rebuild(provider, model, effort):
        calls.append((provider, model, effort))
        return ("m-new", "high") if model else ("", "")

    backend = StubBackend()
    app = TuiApp(
        FakeManager(),
        backend,
        rebuild_ports=rebuild,
        footer=FooterInfo(model="m-a", effort="low", cwd="/w", provider="p-a"),
    )
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    app._candidates = {
        "provider": ["p-a", "p-b"],
        "model": {"p-a": ["m-a", "m-b"], "p-b": ["m-x"]},
        "effort": ["low", "medium", "high"],
    }
    return app, backend, calls


def _strip_rows(backend: StubBackend) -> list[str]:
    """最近一次浮层记录 → 每行纯文本。"""
    return ["".join(s.text for s in line) for line in backend.suggestion_lines[-1]]


def test_bare_model_command_opens_inline_strip_scoped_to_provider():
    """无参 /model → 输入框填 "/model " 弹值候选浮层;仅列当前 provider 的模型,
    当前生效项 ✓,首行默认 › 选中。"""
    app, backend, _ = _make_picker_app()
    backend.submit("/model")
    assert backend.input_texts[-1] == "/model "
    backend.input_changed("/model ")  # textual 异步变更通知
    assert app._suggestions == ["m-a", "m-b"]  # 仅 p-a 的模型,不含 p-b 的 m-x
    rows = _strip_rows(backend)
    assert any("✓" in r and "m-a" in r for r in rows)
    assert rows[0].startswith("› ")


def test_inline_picker_filter_and_navigate_cycles():
    """键入模糊过滤并复位选中;↑↓ 循环导航(复用建议条既有交互)。"""
    app, backend, _ = _make_picker_app()
    backend.submit("/effort")
    backend.input_changed("/effort ")
    assert app._suggestions == ["low", "medium", "high"]
    backend.suggestion_nav(1)
    assert app._suggestion_index == 1
    backend.suggestion_nav(-2)  # 1 - 2 → 循环到尾
    assert app._suggestion_index == 2
    backend.input_changed("/effort med")
    assert app._suggestions == ["medium"]
    assert app._suggestion_index == 0


def test_inline_picker_confirm_applies_and_closes():
    """Enter → rebuild_ports 生效(provider 锁定当前值)、浮层收起、输入清空、状态栏更新。"""
    app, backend, calls = _make_picker_app()
    backend.submit("/model")
    backend.input_changed("/model ")
    backend.suggestion_nav(1)  # 选中 m-b
    backend.suggestion_confirm()
    assert calls == [("p-a", "m-b", None)]
    assert backend.suggestion_lines[-1] == []
    assert backend.input_texts[-1] == ""
    assert app.model.status.model == "m-new"


def test_inline_picker_esc_dismisses_without_apply():
    """Esc → 浮层收起、输入清空,不触发热切换。"""
    app, backend, calls = _make_picker_app()
    backend.submit("/effort")
    backend.input_changed("/effort ")
    backend.interrupt()
    assert backend.suggestion_lines[-1] == []
    assert backend.input_texts[-1] == ""
    assert calls == []


def test_inline_picker_provider_confirm_updates_provider():
    """provider 浮层:✓ 取装配记录;确认后 _provider 更新,模型候选随 provider 切换。"""
    app, backend, calls = _make_picker_app()
    backend.submit("/provider")
    backend.input_changed("/provider ")
    rows = _strip_rows(backend)
    assert any("✓" in r and "p-a" in r for r in rows)
    backend.suggestion_nav(1)
    backend.suggestion_confirm()
    assert calls == [("p-b", None, None)]
    assert app._provider == "p-b"
    backend.input_changed("")  # 清空输入引发的异步通知(消费抑制位)
    backend.submit("/provider")  # 重开:✓ 移到 p-b
    backend.input_changed("/provider ")
    rows = _strip_rows(backend)
    assert any("✓" in r and "p-b" in r for r in rows)
    backend.input_changed("")  # 收起浮层(Esc 语义等价,直接走值语境取消)
    backend.submit("/model")  # 模型候选跟随新 provider
    backend.input_changed("/model ")
    assert app._suggestions == ["m-x"]


def test_suggestion_confirm_opens_inline_picker_for_picker_command():
    """命令建议确认:picker 命令(/mod → model)进入内联选择,条目含描述列。"""
    app, backend, _ = _make_picker_app()
    backend.input_changed("/mod")
    assert app._suggestions[0] == "model"  # 精确前缀优先(mcp 等模糊命中在后)
    row = "".join(s.text for s in backend.suggestion_lines[-1][0])
    assert "/model" in row and "—" in row
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/model "
    backend.input_changed("/model ")  # 异步通知弹值候选浮层
    assert app._suggestion_kind == "value"
    assert app._suggestions == ["m-a", "m-b"]


def test_suggestion_confirm_non_picker_still_fills_input():
    """非 picker 命令(/clear)建议确认 → 保持填入输入框原行为。"""
    app, backend, _ = _make_picker_app()
    backend.input_changed("/cle")
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/clear"


def test_picker_fallback_usage_hint_without_rebuild_ports():
    """候选缺失 / 未注入热切换 → 回退用法提示,不填输入框。"""
    app, backend, _ = _make_app()  # 无 rebuild_ports、无候选
    backend.submit("/model")
    assert backend.input_texts == []
    assert "/model <model" in _rendered_text(app, backend)


# -- /login 密钥配置(tui-login-command) --------------------------------------


def _make_login_app(
    save_fn=None, configured: list[str] | None = None
) -> tuple[TuiApp, StubBackend, list[tuple[str, str]]]:
    """带 login 候选 + 密钥保存器的 app(组合根注入的桩)。"""
    backend = StubBackend()
    manager = FakeManager()
    saved: list[tuple[str, str]] = []

    def save_key(provider: str, key: str) -> tuple[str, str]:
        saved.append((provider, key))
        if save_fn is not None:
            return save_fn(provider, key)
        return "deepseek-v4-flash", "high"

    app = TuiApp(
        manager,
        backend,
        rebuild_ports=lambda *a, **k: ("m-a", "low"),
        save_key=save_key,
        configured_providers=set(configured or []),
        footer=FooterInfo(model="m-a", effort="low", cwd="/w", provider="p-a"),
    )
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    app._candidates = {"login": ["deepseek", "glm", "fake"]}
    return app, backend, saved


def test_login_without_args_opens_picker():
    """无参 /login → 输入框填 "/login " 弹 provider 候选浮层(复用选择器)。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login")
    assert backend.input_texts[-1] == "/login "
    backend.input_changed("/login ")
    assert app._suggestions == ["deepseek", "glm", "fake"]


def test_login_with_provider_enters_mask_mode():
    """带参 /login deepseek → 掩码输入态:提示文案 + 掩码开启。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login deepseek")
    assert app._login_pending == "deepseek"
    assert backend.mask_calls == [True]
    assert backend.placeholders[-1] == "输入 DEEPSEEK_API_KEY,Enter 保存 / Esc 取消"


def test_login_fake_skips_input():
    """/login fake → 提示无需密钥,不进入掩码输入态。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login fake")
    assert app._login_pending is None
    assert backend.mask_calls == []


def test_login_unknown_provider_rejected():
    """/login <未知> → 就地提示,不进入输入态。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login nosuch")
    assert app._login_pending is None
    assert backend.mask_calls == []


def test_login_picker_value_confirm_enters_mask():
    """登录选择器值确认 → 进入掩码输入态(非配置切换)。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login")
    backend.input_changed("/login ")
    backend.suggestion_confirm()  # 首项 deepseek
    assert app._login_pending == "deepseek"
    assert backend.mask_calls == [True]


def test_login_picker_marks_configured_providers():
    """登录选择器:已配置 key 的 provider 打 ✓(组合根注入 configured_providers)。"""
    app, backend, _ = _make_login_app(configured=["glm"])
    backend.submit("/login")
    backend.input_changed("/login ")
    rows = _strip_rows(backend)
    assert any("✓" in r and "glm" in r for r in rows)
    assert not any("✓" in r and "deepseek" in r for r in rows)


def test_login_empty_key_stays_in_input():
    """空密钥提交 → 提示并停留输入态(不退出掩码、不保存)。"""
    app, backend, saved = _make_login_app()
    backend.submit("/login deepseek")
    backend.submit("")
    assert app._login_pending == "deepseek"  # 仍在登录态
    assert backend.mask_calls == [True]  # 掩码未解除
    assert saved == []


def test_login_esc_cancels_without_saving():
    """登录态 Esc → 取消输入,掩码解除,不保存任何内容。"""
    app, backend, saved = _make_login_app()
    backend.submit("/login deepseek")
    backend.interrupt()
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]
    assert saved == []


def test_login_save_success_switches_provider():
    """保存成功 → 写 .env(经注入回调)、状态栏更新、provider 与已配置集更新。"""
    app, backend, saved = _make_login_app()
    backend.submit("/login deepseek")
    backend.submit("sk-secret-1")
    assert saved == [("deepseek", "sk-secret-1")]
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]
    assert app._provider == "deepseek"
    assert app.model.status.model == "deepseek-v4-flash"
    assert "deepseek" in app._configured_providers
    assert "glm" not in app._configured_providers


def test_login_save_value_error_feedback():
    """保存抛 ValueError(未知 provider 等)→ 提示错误并退出输入态。"""
    def boom(provider: str, key: str) -> tuple[str, str]:
        raise ValueError(f"未知的 provider: {provider!r}")

    app, backend, saved = _make_login_app(save_fn=boom)
    backend.submit("/login deepseek")
    backend.submit("sk-x")
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]
    assert saved == [("deepseek", "sk-x")]  # 回调确被调用


def test_login_save_os_error_feedback():
    """保存抛 OSError(磁盘不可写等)→ 提示保存失败并退出输入态。"""
    def boom(provider: str, key: str) -> tuple[str, str]:
        raise OSError("disk full")

    app, backend, _ = _make_login_app(save_fn=boom)
    backend.submit("/login deepseek")
    backend.submit("sk-x")
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]


def test_login_disables_suggestions():
    """登录态建议浮层禁用:输入变化不弹任何候选。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login deepseek")
    backend.input_changed("/pro")
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []


# -- 技能命令(skills-system)--------------------------------------------------


def _sample_skills():
    from codeagent.app.skills import Skill

    return [
        Skill("fmt", "格式化代码。", "/skills/fmt/SKILL.md", "格式化正文"),
        Skill("audit", "依赖审计。", "/skills/audit/SKILL.md", "审计正文"),
    ]


def _make_skills_app(skills=None, diagnostics=None):
    """构造注入技能注册表与诊断的 app(离线断言 /skills /status)。"""
    backend = StubBackend()
    manager = FakeManager()
    app = TuiApp(manager, backend, skills=(skills or [], diagnostics or []))
    backend.on_submit(app._submit)
    backend.on_input_changed(app._on_input_changed)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    return app, backend, manager


def test_skills_command_lists_skills():
    """/skills 无参 → 聊天区列出技能(名称/描述/来源,按名称排序)。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.submit("/skills")
    text = _rendered_text(app, backend)
    assert "可用技能:" in text
    assert "fmt — 格式化代码。 (来源: /skills/fmt/SKILL.md)" in text
    assert text.index("audit") < text.index("fmt")  # 按名称排序
    assert manager_run_texts(app) == []


def test_skills_command_without_skills():
    """/skills 无技能 → 明确说明。"""
    app, backend, _ = _make_skills_app([])
    backend.submit("/skills")
    assert "技能: (无)" in _rendered_text(app, backend)


def test_skills_command_loads_skill():
    """/skills <name> → 渲染块以标注技能名的消息进入会话并触发一轮回复。"""
    app, backend, manager = _make_skills_app(_sample_skills())

    async def _run() -> None:
        backend.submit("/skills fmt")
        await asyncio.sleep(0)

    asyncio.run(_run())
    session = manager.current
    assert len(session.run_texts) == 1
    text = session.run_texts[0]
    assert "[用户手动加载技能: fmt]" in text
    assert '<skill name="fmt" location="/skills/fmt/SKILL.md">' in text
    assert "格式化正文" in text


def test_skills_command_unknown_skill():
    """/skills <未知名> → 明确错误并列出可用技能,不注入不运行。"""
    app, backend, manager = _make_skills_app(_sample_skills())
    backend.submit("/skills nope")
    text = _rendered_text(app, backend)
    assert "未知技能: nope" in text
    assert "fmt" in text and "audit" in text
    assert manager.current.run_texts == []


def test_skills_suggestion_candidates():
    """/skills ␣ → 技能名模糊候选(输入框补全)。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.input_changed("/skills f")
    assert app._suggestions == ["fmt"]
    backend.input_changed("/skills ")
    assert set(app._suggestions) == {"fmt", "audit"}


def test_skills_suggestion_confirm_fills_command():
    """技能候选确认 → 填入 /skills <name>,再次 Enter 即加载。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.input_changed("/skills au")
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/skills audit"
    assert app._suggestions == []
    # 再次提交 → 执行手动加载
    async def _run() -> None:
        backend.submit("/skills audit")
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert "[用户手动加载技能: audit]" in app._manager.current.run_texts[0]


def test_status_shows_skills_and_diagnostics():
    """/status → 技能列表 + 加载诊断可见。"""
    diags = ["shadowed: project 技能 'fmt' 被更高优先级遮蔽", "parse_failed: xxx"]
    app, backend, _ = _make_skills_app(_sample_skills(), diags)
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "技能:" in text
    assert "fmt — 格式化代码。" in text
    assert "技能诊断:" in text
    assert "shadowed" in text and "parse_failed" in text


def manager_run_texts(app: TuiApp) -> list[str]:
    """当前会话的 run 记录(断言命令不触发对话)。"""
    return list(app._manager.current.run_texts)


def test_status_shows_mcp_diagnostics():
    """/status → MCP 装配诊断可见(mcp-client:加载结果可见可断言)。"""
    app, backend, _ = _make_skills_app([], [])
    app._mcp_diagnostics = ["start_failed: MCP server 'bad' 启动失败: x"]
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "MCP:" in text
    assert "start_failed" in text and "bad" in text


def test_status_without_mcp_diagnostics():
    """/status → 无 MCP 诊断时无 MCP 区。"""
    app, backend, _ = _make_app()
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "MCP:" not in text


def test_mcp_command_groups_tools_by_server():
    """/mcp → 按 server 分组列出工具(对齐 Claude /mcp 的 server 维度视图)。"""
    app, backend, manager = _make_app()
    manager.tools = [
        SimpleNamespace(name="read"),
        SimpleNamespace(name="mcp__github__list_issues"),
        SimpleNamespace(name="mcp__github__push"),
        SimpleNamespace(name="mcp__db__query"),
    ]
    app._mcp_diagnostics = ["start_failed: MCP server 'bad' 启动失败: x"]
    backend.submit("/mcp")
    text = _rendered_text(app, backend)
    assert "MCP server:" in text
    assert "github: list_issues, push" in text
    assert "db: query" in text
    assert "start_failed" in text


def test_mcp_command_without_servers():
    """/mcp → 未配置 server 时明确说明。"""
    app, backend, _ = _make_app()
    backend.submit("/mcp")
    assert "MCP: (未配置 server)" in _rendered_text(app, backend)
