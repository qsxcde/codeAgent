"""Rendering scheduler, cache, and viewport behavior tests."""

import asyncio

from codeagent.app.tui.presentation.primitives import Component, RichLine, Span
from codeagent.app.tui.rendering.coordinator import TuiRenderCoordinator
from codeagent.app.tui.rendering.scheduler import FrameScheduler, ResizeDebouncer
from codeagent.app.tui.state.model import TuiModel
from codeagent.app.tui.state.transcript import Transcript
from tests.fixtures.tui import FakeBackend


class CountingComponent(Component):
    def __init__(self, text: str = "line") -> None:
        self.text = text
        self.calls = 0
        super().__init__()

    def render(self, width: int) -> list[RichLine]:
        self.calls += 1
        return [[Span(self.text)]]

    def change(self, text: str) -> None:
        self.text = text
        self.touch()


def test_component_revision_cache_reuses_unchanged_layout() -> None:
    transcript = Transcript()
    block = CountingComponent()
    transcript.append(block)

    transcript.render(80, 10)
    transcript.render(80, 10)
    assert block.calls == 1
    block.change("changed")
    transcript.render(80, 10)
    assert block.calls == 2


def test_viewport_reports_visible_range_and_new_output_count() -> None:
    transcript = Transcript()
    for index in range(20):
        transcript.append(CountingComponent(str(index)))

    transcript.render(80, 5)
    transcript.scroll(5)
    transcript.render(80, 5)
    for index in range(20, 23):
        transcript.append(CountingComponent(str(index)))
    transcript.render(80, 5)

    assert transcript.follow is False
    assert transcript.new_output_count == 3
    start, end = transcript.visible_range
    assert end - start == 5
    assert transcript.layout_index
    assert transcript.overscan_range[0] <= start
    assert transcript.overscan_range[1] >= end
    transcript.scroll_to_bottom()
    transcript.render(80, 5)
    assert transcript.new_output_count == 0


def test_viewport_does_not_render_offscreen_blocks() -> None:
    transcript = Transcript()
    blocks = [CountingComponent(str(index)) for index in range(200)]
    for block in blocks:
        transcript.append(block)

    transcript.render(80, 5)

    assert sum(block.calls for block in blocks) <= 9
    assert sum(block.calls for block in blocks) < len(blocks)


def test_frame_scheduler_coalesces_requests_and_caps_refresh_rate() -> None:
    scheduler = FrameScheduler(target_fps=30)
    assert scheduler.request(0.0) is True
    assert scheduler.request(0.001) is False
    scheduler.complete(0.0)
    assert scheduler.request(0.010) is False
    assert scheduler.request(0.034) is True


async def test_resize_debouncer_runs_once_after_burst() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        debouncer = ResizeDebouncer(lambda: calls.append("resize"), delay=0.0)
        debouncer.notify()
        debouncer.notify()
        debouncer.notify()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert calls == ["resize"]

    await (scenario())


async def test_immediate_flush_cancels_already_queued_frame() -> None:
    """提交屏障立即刷新后,旧的 call_soon 帧不会再次覆盖或重复提交。"""
    backend = FakeBackend()
    coordinator = TuiRenderCoordinator(TuiModel(), backend)
    coordinator.schedule_render()

    coordinator.flush_render_now()
    await asyncio.sleep(0)

    assert len(backend.renders) == 1


async def test_direct_flush_cancels_already_queued_frame() -> None:
    """普通直接 flush 也不会遗留已经排队的回调。"""
    backend = FakeBackend()
    coordinator = TuiRenderCoordinator(TuiModel(), backend)
    coordinator.schedule_render()

    coordinator.flush_render()
    await asyncio.sleep(0)

    assert len(backend.renders) == 1
