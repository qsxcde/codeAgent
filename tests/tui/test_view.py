"""tests/tui/test_view.py:TuiApp 视图逻辑(注入 stub 后端,不 import textual)。

对应 spec「运行中打断」「空闲退出」「帧率达标」(渲染合并)、「工具调用点击展开」
(点击路由)、「双端底部状态条」(footer 富样式传递)。
"""

import asyncio
from types import SimpleNamespace
from typing import Any

from codeagent.app.tui.components import FooterInfo, ToolCallBlock, rich_to_plain
from codeagent.app.tui.commands import Command
from codeagent.app.tui.view import TuiApp
from codeagent.core.events import AgentEvent, EventType
from codeagent.core.messages import Message
from codeagent.session.store import UsageStats


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
        # cost-transparency:缺省全零用量(load_usage 空态)。
        self.usage = UsageStats()
        self.history: list[Message] = []

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
        self.timestamp = f"2026-08-21T00:00:00.{len(FakeSession._created):03d}"
        self.title = f"标题-{session.session_id}"
        self.parent_session = None  # session-tree:树视图读父会话 id


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
        refs = [FakeRef(s) for s in self.sessions]
        refs.sort(key=lambda r: (r.timestamp, r.id))
        return refs

    def continue_recent(self):
        refs = self.list()
        if not refs:
            return self.create()
        return self.switch(refs[-1].id)

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


def test_session_switch_refreshes_skill_registry_and_diagnostics():
    """切换会话后 TUI 应重读 Adapter/Registry 视图，而非保留启动快照。"""
    backend = StubBackend()
    manager = FakeManager()
    refreshed = []

    def refresh_skills():
        refreshed.append(True)
        return ([
            SimpleNamespace(
                name="using-superpowers",
                description="bootstrap",
                path="/pkg/using-superpowers/SKILL.md",
                package_id="superpowers",
                package_version="6.3.0",
                package_scope="user",
                bootstrap=True,
            )
        ], ["package_reload: ok"])

    app = TuiApp(
        manager,
        backend,
        skills=([], []),
        refresh_skills=refresh_skills,
    )
    manager.create()
    app._cmd_sessions(Command("sessions", ("new",), "new"))

    assert refreshed
    assert app._skills_by_name["using-superpowers"].package_id == "superpowers"
    assert app._skill_diagnostics == ["package_reload: ok"]


def test_skills_package_subcommand_is_forwarded_to_composition_root():
    """/skills Package 子命令由组合根执行，TUI 仅刷新并展示结果。"""
    backend = StubBackend()
    manager = FakeManager()
    calls = []

    def package_action(action, args):
        calls.append((action, args))
        return "已安装 Package demo"

    app = TuiApp(manager, backend, package_action=package_action)
    app._cmd_skills(Command("skills", ("install", "./demo"), "install ./demo"))

    assert calls == [("install", ("./demo",))]
    assert "已安装 Package demo" in "\n".join(app.model.transcript.all_lines(120))


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


def test_context_usage_is_synced_to_footer_status():
    """最近一次请求的上下文占用会同步到状态栏右侧。"""
    backend = StubBackend()
    session = FakeSession()
    session.context_tokens = 12_400
    session.context_window = 128_000
    app = TuiApp(FakeManager(session), backend)

    app._flush_render()

    plain = "".join(span.text for span in backend.statuses[-1])
    assert plain.endswith("上下文 12.4k / 128k · 9.7%")
    assert app.model.status.context_tokens == 12_400
    assert app.model.status.context_window == 128_000


def test_status_command_includes_runtime_and_render_diagnostics():
    app, backend, _ = _make_app()
    app.model.apply(
        AgentEvent(
            EventType.ERROR,
            payload="模型不可用",
            metadata={
                "error_code": "provider_unavailable",
                "retryable": True,
                "side_effect_state": "none",
            },
        )
    )
    backend.submit("/status")
    text = "\n".join(app.model.transcript.all_lines(120))
    assert "阶段: 失败" in text
    assert "错误码: provider_unavailable" in text
    assert "可重试: 是" in text
    assert "渲染:" in text
    assert "输出:" in text


def test_submit_is_gated_during_restore_and_compaction():
    app, backend, manager = _make_app()
    app.model.apply(AgentEvent(EventType.RESTORE_STARTED))
    backend.submit("普通消息")
    assert manager.current.run_texts == []
    app.model.apply(AgentEvent(EventType.RESTORE_FINISHED))
    app.model.apply(AgentEvent(EventType.COMPACTION_STARTED))
    backend.submit("另一条消息")
    assert manager.current.run_texts == []


def test_retry_command_requires_safe_failure_and_continue_starts_new_prompt():
    app, backend, manager = _make_app()
    manager.current.last_failure = {
        "retryable": False,
        "cleanup_uncertain": True,
        "side_effect_state": "uncertain",
        "prompt": "old tool call",
    }
    backend.submit("/retry")
    assert "不可安全重试" in "\n".join(app.model.transcript.all_lines(120))
    backend.submit("/continue new plan")
    assert manager.current.run_texts == ["new plan"]


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


def test_quit_command_dispatches_and_exits():
    """/quit 命令 → 等同 Ctrl+C 退出(空闲态打印完整文档)。"""
    app, backend, manager = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))
    backend.on_submit(app._submit)
    backend.submit("/quit")
    assert backend.exited is not None
    doc = "\n".join(backend.exited)
    assert "hi" in doc
    assert "回复" in doc


def test_quit_command_running_is_ignored():
    """/quit 命令运行中 → 输入框提交被忽略(与其他命令一致,不退出)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    backend.on_submit(app._submit)
    backend.submit("/quit")
    assert backend.exited is None
    assert manager.current.aborted is False


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


def test_render_scheduler_delays_frames_inside_target_interval():
    app, backend, manager = _make_app()

    async def scenario() -> None:
        backend.resize()
        await asyncio.sleep(0)
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="a"))
        await asyncio.sleep(0)
        before = len(backend.renders)
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="b"))
        await asyncio.sleep(0)
        assert len(backend.renders) == before
        await asyncio.sleep(0.04)
        assert len(backend.renders) == before + 1

    asyncio.run(scenario())


def test_large_restore_never_hydrates_live_model_in_worker(monkeypatch):
    app, _, manager = _make_app()
    session = manager.current
    session.history = [Message(role="user", content=f"m-{i}") for i in range(1001)]
    calls: list[Any] = []

    async def fake_to_thread(fn, *args):
        calls.append(fn)
        return fn(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def scenario() -> None:
        await app._restore_large_session(session)

    asyncio.run(scenario())

    assert calls
    assert all(getattr(fn, "__self__", None) is not app.model for fn in calls)


def test_large_restore_drops_result_after_session_switch(monkeypatch):
    app, _, manager = _make_app()
    session = manager.current
    session.history = [Message(role="user", content=f"old-{i}") for i in range(1001)]
    calls = 0

    async def fake_to_thread(fn, *args):
        nonlocal calls
        calls += 1
        result = fn(*args)
        if calls == 2:
            manager.create()
        return result

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def scenario() -> None:
        await app._restore_large_session(session)

    asyncio.run(scenario())

    assert not any("old-" in line for line in app.model.transcript.all_lines(80))

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


def test_status_shows_usage_line_with_cache_hit():
    """/status → 用量行:输入/输出(含推理)/缓存命中率(约,含原始计数)。"""
    app, backend, manager = _make_app()
    manager.current.usage = UsageStats(
        input_tokens=1000, output_tokens=30, reasoning_tokens=20, cached_tokens=400
    )
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "用量: 输入 1000 · 输出 50 · 缓存命中约 40.0% (400/1000)" in text


def test_status_shows_usage_empty_state():
    """/status → 无用量记录时显示空态,不展示误导性数值。"""
    app, backend, manager = _make_app()
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "用量: (无)" in text
    assert "缓存命中" not in text


def test_status_usage_cache_ratio_clamped():
    """/status → 缓存命中率钳制:命中 > 输入时显示 100%(不超界误导)。"""
    app, backend, manager = _make_app()
    manager.current.usage = UsageStats(input_tokens=100, cached_tokens=300)
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "缓存命中约 100.0% (300/100)" in text


def test_tools_command_lists_tool_names():
    """/tools → 列出可用工具。"""
    app, backend, manager = _make_app()
    manager.tools = [type("T", (), {"name": "bash"})(), type("T", (), {"name": "read"})()]
    backend.submit("/tools")
    text = _rendered_text(app, backend)
    assert "bash" in text and "read" in text


def test_sessions_list_switch_and_new():
    """/sessions:列表 / <id> 切换 / new 新建 / recent 恢复最近。"""
    app, backend, manager = _make_app()
    first = manager.current

    backend.submit("/sessions list")
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


def test_switching_session_hydrates_transcript_and_context_status():
    """切换会话会替换 transcript,并同步目标会话的上下文占用。"""
    app, backend, manager = _make_app()
    first = manager.current
    first.history = [Message(role="user", content="之前的问题"), Message(role="assistant", content="之前的回答")]
    first.context_tokens = 12_400
    first.context_window = 128_000
    other = manager.create()
    other.history = [Message(role="user", content="另一个问题"), Message(role="assistant", content="另一个回答")]
    other.context_tokens = 2_000
    other.context_window = 32_000

    backend.submit(f"/sessions {other.session_id}")
    text = _rendered_text(app, backend)
    assert "另一个问题" in text and "之前的问题" not in text
    assert app.model.status.context_tokens == 2_000
    assert app.model.status.context_window == 32_000


def test_sessions_recent_restores_last_session():
    """/sessions recent → 恢复最近会话(continue_recent);无会话时新建。"""
    app, backend, manager = _make_app()
    first = manager.current
    backend.submit("/sessions new")
    assert manager.current is not first
    backend.submit("/sessions recent")
    # continue_recent 取最近创建(时间升序末位)= first 之后的会话。
    assert manager.current is not first
    text = _rendered_text(app, backend)
    assert "已恢复最近会话" in text


def test_sessions_no_args_opens_inline_picker():
    """/sessions 无参 → 交互式选择器(命令名确认后弹会话候选浮层)。"""
    app, backend, manager = _make_app()
    backend.submit("/sessions")
    # 无参走 _open_inline_picker("sessions"):输入框填入 "/sessions " 触发候选。
    assert backend.input_texts[-1] == "/sessions "
    # 输入变更 → 候选 = 会话 id 列表
    backend.input_changed("/sessions ")
    assert app._suggestion_kind == "value"
    assert manager.current.session_id in app._suggestions


def test_sessions_picker_confirm_switches_session():
    """/sessions 选择器值确认 → 切换到所选会话(订阅跟随既有)。"""
    app, backend, manager = _make_app()
    first = manager.current
    backend.submit("/sessions new")
    other = manager.current
    backend.submit("/sessions")
    backend.input_changed("/sessions ")
    # 选中 first(历史会话)→ 确认切换
    app._suggestions = [first.session_id, other.session_id]
    app._suggestion_index = 0
    app._on_suggestion_confirm()
    assert manager.current is first
    text = _rendered_text(app, backend)
    assert "已切换到会话" in text


def test_sessions_picker_empty_state():
    """/sessions 无会话时选择器显示空态提示(不切换)。"""
    app, backend, manager = _make_app()
    manager.sessions = []  # 无任何历史会话
    manager.current = None
    backend.submit("/sessions")
    text = _rendered_text(app, backend)
    assert "暂无历史会话" in text


# -- 会话树(session-tree /tree 与 /sessions list 缩进)------------------------


def _make_forked_manager() -> tuple[TuiApp, StubBackend, FakeManager]:
    """构造 A(根)→ B(fork 自 A)的会话对,供树展示断言。"""
    app, backend, manager = _make_app()
    root = manager.current  # A
    branch = manager.fork(root.session_id)  # B:fork 自 A
    # FakeManager.fork 的 FakeRef 无 parent 关联:显式挂钩 A。
    orig = manager.list

    def _list():
        refs = orig()
        for ref in refs:
            if ref.id == branch.session_id:
                ref.parent_session = root.session_id
        return refs

    manager.list = _list  # type: ignore[method-assign]
    return app, backend, manager


def test_tree_command_shows_fork_chain():
    """/tree → 展示 fork 链树(缩进 + 分支字符,含标题与 id)。"""
    app, backend, manager = _make_forked_manager()
    backend.submit("/tree")
    text = _rendered_text(app, backend)
    assert "会话树:" in text
    root = manager.current
    assert root.session_id in text
    # 分支 B 以缩进行展示于 A 下(含分支字符)。
    branch = manager.list()[-1]
    assert "├─" in text or "└─" in text
    assert branch.title in text


def test_tree_command_switches_session():
    """/tree <id> → 切换到指定会话(订阅跟随既有)。"""
    app, backend, manager = _make_forked_manager()
    branch_id = manager.list()[-1].id
    root_id = manager.current.session_id
    backend.submit(f"/tree {branch_id}")
    assert manager.current.session_id == branch_id
    backend.submit(f"/tree {root_id}")
    assert manager.current.session_id == root_id


def test_tree_command_unknown_session():
    """/tree <id> 会话不存在 → 就地报错,不切换。"""
    app, backend, manager = _make_forked_manager()
    before = manager.current
    backend.submit("/tree ghost")
    text = _rendered_text(app, backend)
    assert "会话不存在" in text
    assert manager.current is before


def test_tree_command_empty_state():
    """/tree 无会话 → 空态提示。"""
    app, backend, manager = _make_app()
    manager.sessions = []
    manager.current = None
    backend.submit("/tree")
    text = _rendered_text(app, backend)
    assert "(暂无会话)" in text


def test_sessions_list_shows_tree_indentation():
    """/sessions list → 父子缩进展示(子分支缩进于父下),孤儿平级。"""
    app, backend, manager = _make_forked_manager()
    backend.submit("/sessions list")
    text = _rendered_text(app, backend)
    assert "会话列表:" in text
    assert "├─" in text or "└─" in text
    # 根与分支标题均可见(树渲染用 FakeRef.title)。
    refs = manager.list()
    root_ref = refs[0]
    branch_ref = refs[-1]
    assert root_ref.title in text
    assert branch_ref.title in text


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
    """(回归:D2)单独输入 / 展示全量命令建议(注册表原序)。

    回归(cost-transparency):候选列表必须容纳注册表全量——按 fuzzy_rank
    排名截断会把排后命令(如 /quit /fork /compact /skills /mcp)永久隐藏;
    渲染层用固定窗口裁剪视口,但候选本身不截断(浮层可滚动到达全部)。
    """
    from codeagent.app.tui.commands import default_registry

    app, backend, _ = _make_app()
    backend.input_changed("/")
    # 候选列表 = 注册表全量(原序),不按排名截断。
    assert app._suggestions == list(default_registry())


def test_suggestion_window_fixed_height_and_scrolls():
    """补全浮层固定窗口:候选多于窗口时渲染行数 = 窗口高,高亮居中跟随。

    - 首屏:渲染 _SUGGESTION_WINDOW 行(非全量),高亮第 1 条;
    - 下移:高亮进入窗口中部后,窗口起点跟随滚动;
    - 末条:窗口底部对齐,高亮可见(不被顶出窗口)。
    """
    from codeagent.app.tui.view import _SUGGESTION_WINDOW

    app, backend, _ = _make_app()
    # 用注册表全量命令(14 条 > 窗口 9)验证固定窗口滚动。
    from codeagent.app.tui.commands import default_registry

    names = list(default_registry())
    assert len(names) > _SUGGESTION_WINDOW  # 前提:候选多于窗口
    app._suggestions = list(names)
    app._suggestion_index = 0
    app._suggestion_kind = "command"
    app._render_suggestions()
    rendered = backend.suggestion_lines[-1]
    assert len(rendered) == _SUGGESTION_WINDOW  # 固定窗口高,非 14 行全量
    # 首行 = 首候选且高亮
    first_text = "".join(span.text for span in rendered[0])
    assert names[0] in first_text and "›" in first_text

    # 下移 10 次:高亮进入中部后窗口起点跟随滚动(可见窗口不再从 0 起)。
    for _ in range(10):
        app._on_suggestion_navigate(1)
    rendered = backend.suggestion_lines[-1]
    first_text = "".join(span.text for span in rendered[0])
    assert names[0] not in first_text  # 窗口已滚动,首行不是首候选

    # 末条:窗口底部对齐,末候选高亮可见(不被顶出窗口)。
    app._suggestion_index = len(names) - 1
    app._render_suggestions()
    rendered = backend.suggestion_lines[-1]
    last_text = "".join(span.text for span in rendered[-1])
    assert names[-1] in last_text and "›" in last_text


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
        Skill(
            "brainstorming",
            "创意工作前澄清需求与目标，避免在需求不明确时直接开始实现。这个描述很长，列表中应该被截断。",
            "/packages/superpowers/skills/brainstorming/SKILL.md",
            "头脑风暴正文",
            package_id="superpowers",
            package_version="6.3.0",
            package_scope="user",
        ),
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
    """/skills 无参 → 紧凑分组列表，不重复展示路径和 Package 元数据。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.submit("/skills")
    text = _rendered_text(app, backend)
    assert "可用技能 (2)" in text
    assert "superpowers · 1" in text
    assert "本地技能 · 1" in text
    assert "brainstorming" in text and "fmt" in text
    assert "/packages/superpowers" not in text
    assert "Package: superpowers" not in text
    assert "应该被截断" not in text
    assert manager_run_texts(app) == []


def test_skills_info_shows_full_metadata_for_one_skill():
    """/skills info <name> → 详情页展示完整路径、Package 和版本。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.submit("/skills info brainstorming")
    text = _rendered_text(app, backend)

    assert "技能详情" in text
    assert "名称: brainstorming" in text
    assert "来源: /packages/superpowers/skills/brainstorming/SKILL.md" in text
    assert "Package: superpowers@6.3.0 (user)" in text


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
    assert "fmt" in text and "brainstorming" in text
    assert manager.current.run_texts == []


def test_skills_suggestion_candidates():
    """/skills ␣ → 技能名模糊候选(输入框补全)。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.input_changed("/skills f")
    assert app._suggestions == ["fmt"]
    backend.input_changed("/skills ")
    assert set(app._suggestions) == {"fmt", "brainstorming"}


def test_skills_suggestion_confirm_fills_command():
    """技能候选确认 → 填入 /skills <name>,再次 Enter 即加载。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.input_changed("/skills br")
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/skills brainstorming"
    assert app._suggestions == []
    # 再次提交 → 执行手动加载
    async def _run() -> None:
        backend.submit("/skills brainstorming")
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert "[用户手动加载技能: brainstorming]" in app._manager.current.run_texts[0]


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


def test_status_shows_package_and_bootstrap_metadata():
    """/status 显示 Package 来源、revision 和 Bootstrap 状态。"""
    from codeagent.app.skills import Skill

    skill = Skill(
        "using-superpowers",
        "启动引导。",
        "/packages/superpowers/skills/using-superpowers/SKILL.md",
        "引导正文",
        package_id="superpowers",
        package_version="6.3.0",
        package_scope="user",
        bootstrap=True,
    )
    app, backend, _ = _make_skills_app([skill])
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "Bootstrap: using-superpowers" in text
    assert "Package: superpowers@6.3.0 (user)" in text


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
