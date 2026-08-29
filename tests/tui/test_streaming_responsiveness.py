"""真实 Textual 事件循环下的流式交互回归。"""

from __future__ import annotations

import asyncio

import pytest

from codeagent.app.tui.adapters.textual.backend import TextualBackend
from codeagent.app.tui.application import TuiApp
from codeagent.app.tui.presentation.blocks import AssistantBlock
from codeagent.core.contracts.events import AgentEvent, EventType
from tests.tui.view.fixtures import FakeManager, FakeSession
from tests.tui.performance_helpers import (
    assert_control_latency,
    assert_event_order,
    assert_text_complete,
)


pytestmark = pytest.mark.integration


class StreamingFakeSession(FakeSession):
    """持续发出增量、直到收到 abort 的离线会话。"""

    def __init__(self) -> None:
        super().__init__("streaming")
        self.started = asyncio.Event()
        self.ready = asyncio.Event()
        self.emitted_text: list[str] = []
        self.event_types: list[str] = []
        self.interaction_trace: list[tuple[str, float]] = []
        self.abort_at: float | None = None
        self.paused = False
        self.resume = asyncio.Event()

    def emit_event(self, event: AgentEvent) -> None:
        self.event_types.append(event.type)
        self._emit(event)

    def record_interaction(self, name: str) -> None:
        self.interaction_trace.append((name, asyncio.get_running_loop().time()))

    async def stream(self) -> None:
        self.emit_event(AgentEvent(EventType.SESSION_STARTED, payload="prompt"))
        self.started.set()
        index = 0
        while not self.aborted:
            if self.paused:
                await self.resume.wait()
                self.resume.clear()
                continue
            chunk = f"stream line {index:04d} " + "x" * 24 + "\n"
            self.emitted_text.append(chunk)
            self.emit_event(AgentEvent(EventType.TEXT_DELTA, payload=chunk))
            index += 1
            if index == 120:
                self.ready.set()
                self.paused = True
            await asyncio.sleep(0)
        self.emit_event(AgentEvent(EventType.RUN_CANCELLED))

    def abort(self) -> None:
        self.abort_at = asyncio.get_running_loop().time()
        super().abort()
        self.resume.set()


def _wire_app(
    app: TuiApp, backend: TextualBackend, session: StreamingFakeSession | None = None
) -> None:
    """复用生产 start() 的 callback 装配,但不启动阻塞式 run。"""
    def record(name: str, callback):
        def wrapped(*args):
            if session is not None:
                session.record_interaction(name)
            return callback(*args)

        return wrapped

    backend.on_submit(record("submit", app._submit))
    backend.on_interrupt(record("interrupt", app._interrupt))
    backend.on_quit(app._quit)
    backend.on_resize(app._schedule_render)
    backend.on_click(app._click)
    backend.on_input_changed(record("input", app._on_input_changed))
    backend.on_suggestion_navigate(app._on_suggestion_navigate)
    backend.on_suggestion_confirm(app._on_suggestion_confirm)
    backend.on_scroll(record("scroll", app._on_scroll))
    backend.on_confirmation_response(record("confirmation", app._on_confirmation_response))


async def _finish_stream(app: TuiApp, session: StreamingFakeSession, task: asyncio.Task[None]) -> None:
    """结束 fake stream 并清理协作式帧任务,避免测试跨用例泄漏。"""
    if not task.done():
        session.abort()
    await task
    app._render_coordinator.cancel_pending_render()
    await asyncio.sleep(0)


async def test_textual_streaming_keeps_input_and_escape_responsive() -> None:
    """高频输出期间输入草稿不丢失,Esc 在同一真实事件循环内触发 abort。"""
    session = StreamingFakeSession()
    manager = FakeManager(session)
    backend = TextualBackend()
    app = TuiApp(manager, backend)
    _wire_app(app, backend, session)

    async with backend._app.run_test(size=(80, 24)) as pilot:
        stream_task = asyncio.create_task(session.stream())
        try:
            await session.started.wait()
            await session.ready.wait()
            await pilot.press(*list("draft"))
            assert backend._app.composer.input.text == "draft"

            requested_at = asyncio.get_running_loop().time()
            await pilot.press("escape")
            assert session.abort_at is not None
            assert_control_latency([(session.abort_at - requested_at) * 1000])
            interaction_names = [name for name, _ in session.interaction_trace]
            assert "input" in interaction_names
            assert "interrupt" in interaction_names
            await _finish_stream(app, session, stream_task)

            assistant = next(
                block for block in app.model.transcript.blocks if isinstance(block, AssistantBlock)
            )
            assert_text_complete(assistant.body, "".join(session.emitted_text))
            assert session.event_types[-1] == EventType.RUN_CANCELLED
        finally:
            await _finish_stream(app, session, stream_task)


async def test_textual_streaming_handles_scroll_and_confirmation_in_order() -> None:
    """高频输出期间 PageUp 与确认键仍可达,结构事件保持前置增量顺序。"""
    session = StreamingFakeSession()
    manager = FakeManager(session)
    backend = TextualBackend()
    app = TuiApp(manager, backend)
    _wire_app(app, backend, session)

    async with backend._app.run_test(size=(80, 24)) as pilot:
        stream_task = asyncio.create_task(session.stream())
        try:
            await session.started.wait()
            await session.ready.wait()
            app._flush_render_now()
            await pilot.press("pageup")
            assert app.model.transcript.follow is False

            session.emit_event(
                AgentEvent(
                    EventType.TOOL_CALL,
                    payload=[{"name": "bash", "args": {"command": "echo ok"}, "id": "c1"}],
                )
            )
            session.emit_event(
                AgentEvent(
                    EventType.CONFIRMATION_REQUESTED,
                    payload={
                        "request_id": "r1",
                        "tool_call_id": "c1",
                        "tool": "bash",
                        "summary": "echo ok",
                        "reason": "test",
                    },
                )
            )
            await pilot.pause()
            assert backend.confirmation_active
            await pilot.press("y")
            assert session.approvals == [("r1", True)]
            interaction_names = [name for name, _ in session.interaction_trace]
            assert "scroll" in interaction_names
            assert "confirmation" in interaction_names

            assert_event_order(
                session.event_types,
                [EventType.TEXT_DELTA, EventType.TOOL_CALL, EventType.CONFIRMATION_REQUESTED],
            )
            blocks = app.model.transcript.blocks
            assistant_index = next(
                index for index, block in enumerate(blocks) if isinstance(block, AssistantBlock)
            )
            tool_index = next(index for index, block in enumerate(blocks) if block.__class__.__name__ == "ToolCallBlock")
            assert assistant_index < tool_index
        finally:
            await _finish_stream(app, session, stream_task)
