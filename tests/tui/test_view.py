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
    """记录渲染/状态/底部状态条/退出文档/点击的假后端(替代 textual,离线断言)。"""

    def __init__(self) -> None:
        self.renders: list[Any] = []
        self.statuses: list[Any] = []
        self.footers: list[Any] = []
        self.submit = None
        self.interrupt = None
        self.resize = None
        self.click = None
        self.exited: list[str] | None = None

    def run(self) -> None:  # pragma: no cover - stub
        pass

    def transcript_size(self) -> tuple[int, int]:
        return 60, 10

    def render(self, lines) -> None:
        self.renders.append(list(lines))

    def set_status(self, line) -> None:
        self.statuses.append(line)

    def set_footer(self, line) -> None:
        self.footers.append(line)

    def on_submit(self, handler) -> None:
        self.submit = handler

    def on_interrupt(self, handler) -> None:
        self.interrupt = handler

    def on_resize(self, handler) -> None:
        self.resize = handler

    def on_click(self, handler) -> None:
        self.click = handler

    def exit_document(self, lines: list[str]) -> None:
        self.exited = list(lines)

    def stop(self) -> None:  # pragma: no cover - stub
        pass


class FakeSession:
    """假会话:订阅回调可按需触发事件;abort 记录调用。"""

    def __init__(self) -> None:
        self.subscribers: list[Any] = []
        self.aborted = False

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


def _make_app() -> tuple[TuiApp, StubBackend, FakeSession]:
    backend = StubBackend()
    session = FakeSession()
    app = TuiApp(session, backend)
    backend.on_submit(app._submit)
    backend.on_interrupt(app._interrupt)
    backend.on_resize(app._schedule_render)
    backend.on_click(app._click)
    return app, backend, session


def test_submit_starts_run_and_renders():
    """提交触发会话运行,事件驱动渲染(对应 spec「对话输入与回复渲染」)。"""
    app, backend, session = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        backend.submit("你好")
        await asyncio.sleep(0)

    asyncio.run(_run())
    rendered_plain = ["".join(rich_to_plain(lines)) for lines in backend.renders]
    assert any("你好" in text for text in rendered_plain)
    assert "ok" in rendered_plain[-1]
    assert app.model.status.status == "IDLE"
    # 状态栏与 footer 均以富样式行传递(design D5)
    assert backend.statuses and all(isinstance(s, list) for s in backend.statuses)
    assert backend.footers and "● ready" in "".join(s.text for s in backend.footers[-1])


def test_footer_rich_line_seeded_and_passed():
    """footer 的 model · effort 经装配注入并以富样式传给后端(spec「双端底部状态条」)。"""
    backend = StubBackend()
    session = FakeSession()
    app = TuiApp(session, backend, footer=FooterInfo(model="qwen3.8-max", effort="high"))
    backend.on_resize(app._schedule_render)

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert backend.footers, "footer 未渲染"
    plain = "".join(s.text for s in backend.footers[-1])
    assert "● ready" in plain
    assert "qwen3.8-max · high" in plain


def test_interrupt_running_aborts():
    """运行中 Esc → abort(对应 spec「运行中打断」)。"""
    app, backend, session = _make_app()
    app.model.running = True
    backend.interrupt()
    assert session.aborted is True


def test_interrupt_idle_exits_with_doc():
    """空闲 Esc → 退出并打印完整文档(对应 spec「空闲退出」「退出完整文档」)。"""
    app, backend, session = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))  # 结束本轮 → 空闲
    backend.interrupt()
    assert backend.exited is not None
    doc = "\n".join(backend.exited)
    assert "hi" in doc
    assert "回复" in doc


def test_run_cancelled_event_returns_idle():
    """RUN_CANCELLED 事件 → 状态栏回 IDLE(对应 spec「状态栏实时反馈」)。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    assert app.model.running is True
    assert app.model.footer.status_text == "running"
    app.model.apply(AgentEvent(EventType.RUN_CANCELLED))
    assert app.model.running is False
    assert app.model.status.status == "IDLE"
    assert app.model.footer.status_text == "ready"


def test_render_coalescing():
    """N 个增量事件合并成一次渲染(对应 spec「帧率达标」;design D4)。"""
    app, backend, session = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        before = len(backend.renders)
        # 同一循环迭代内连发多个增量
        session._emit(AgentEvent(EventType.TEXT_DELTA, payload="a"))
        session._emit(AgentEvent(EventType.TEXT_DELTA, payload="b"))
        session._emit(AgentEvent(EventType.TEXT_DELTA, payload="c"))
        await asyncio.sleep(0)
        assert len(backend.renders) - before == 1

    asyncio.run(_run())


def test_click_toggles_tool_expand():
    """点击工具行 → 切换折叠(spec「工具调用点击展开」;design D4)。"""
    app, backend, session = _make_app()
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
