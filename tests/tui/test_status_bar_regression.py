"""V4-19 状态栏计时与刷新回归测试。"""

from __future__ import annotations

import asyncio

from codeagent.app.tui.presentation.primitives import _cell_width
from codeagent.app.tui.presentation.status import StatusBar
from codeagent.app.tui.rendering.coordinator import TuiRenderCoordinator
from codeagent.app.tui.state.model import TuiModel
from codeagent.app.tui.state.runtime import RuntimePhase, RuntimeSnapshot
from codeagent.core.contracts.events import AgentEvent, EventType


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class StatusBackend:
    def __init__(self) -> None:
        self.renders: list[object] = []
        self.statuses: list[object] = []

    def transcript_size(self) -> tuple[int, int]:
        return 100, 10

    def render(self, lines) -> None:
        self.renders.append(lines)

    def set_status(self, line) -> None:
        self.statuses.append(line)


def _status_text(model: TuiModel, width: int = 100) -> str:
    return "".join(span.text for span in model.status.render(width)[0])


def _cells(text: str) -> int:
    return _cell_width(text)


def _divider_cells(text: str) -> list[int]:
    positions: list[int] = []
    offset = 0
    for char in text:
        if char == "│":
            positions.append(offset)
        offset += _cell_width(char)
    return positions


def test_task_elapsed_is_independent_from_runtime_and_freezes_at_terminal_state() -> None:
    clock = FakeClock(10.0)
    model = TuiModel(clock=clock)
    model.status.apply_snapshot(
        RuntimeSnapshot(phase=RuntimePhase.STREAMING, phase_started_at=0.0), now=clock()
    )
    model.status.set_task_status("verifying", command="pytest")

    clock.value = 13.0
    model.refresh_status_clock()
    assert " 03.0s" in _status_text(model)
    assert " 10.0s" not in _status_text(model)

    model.status.set_task_status("verified", message="验证完成")
    clock.value = 20.0
    model.refresh_status_clock()
    assert " 03.0s" in _status_text(model)
    assert " 10.0s" not in _status_text(model)


def test_task_phase_changes_reset_active_elapsed_and_terminal_states_are_stable() -> None:
    clock = FakeClock()
    model = TuiModel(clock=clock)
    model.status.set_task_status("verifying", command="pytest")

    clock.value = 5.0
    model.refresh_status_clock()
    assert model.status.task_elapsed_ms == 5000

    model.status.set_task_status("repairing", command="ruff")
    assert model.status.task_elapsed_ms == 0
    clock.value = 7.0
    model.refresh_status_clock()
    assert model.status.task_elapsed_ms == 2000

    model.status.set_task_status("failed", message="验证失败")
    frozen = model.status.task_elapsed_ms
    assert frozen == 2000
    assert model.status.status_clock_active is False
    clock.value = 20.0
    model.refresh_status_clock()
    assert model.status.task_elapsed_ms == frozen


def test_task_terminal_labels_keep_three_zone_boundaries_across_widths() -> None:
    terminal_labels = {
        "verified": "已验证",
        "unverified": "未验证",
        "failed": "验证失败",
        "cancelled": "已取消",
        "no_changes": "无变更",
    }
    widths = (39, 40, 41, 55, 56, 57, 63, 64, 65, 87, 88, 89, 119, 120, 121)

    for width in widths:
        bar_texts: list[str] = []
        for phase, label in terminal_labels.items():
            bar = StatusBar(clock=lambda: 12.0)
            bar.model = "模型-名称"
            bar.cwd = "/a/very/long/工作目录"
            bar.context_tokens = 100_000
            bar.context_window = 128_000
            bar.set_task_status(
                phase,
                command="python -m pytest tests/very/long/test_command.py --full",
            )
            text = "".join(span.text for span in bar.render(width)[0])
            bar_texts.append(text)
            assert label in text
            assert _cells(text) == width
        assert len({tuple(_divider_cells(text)) for text in bar_texts}) == 1


async def test_status_timer_refreshes_without_agent_events() -> None:
    clock = FakeClock()
    model = TuiModel(clock=clock)
    model.status.set_task_status("verifying", command="pytest")
    backend = StatusBackend()
    coordinator = TuiRenderCoordinator(
        model, backend, status_refresh_interval=0.001
    )

    coordinator.flush_render()
    initial_status_count = len(backend.statuses)
    coordinator.sync_status_timer()
    clock.value = 4.0
    for _ in range(20):
        await asyncio.sleep(0.001)
        if len(backend.statuses) > initial_status_count:
            break

    assert len(backend.statuses) > initial_status_count
    assert any(" 04.0s" in "".join(span.text for span in line) for line in backend.statuses)

    coordinator.stop_status_timer()
    await asyncio.sleep(0)
    assert coordinator.status_task is None


async def test_runtime_status_timer_refreshes_without_task_events() -> None:
    clock = FakeClock()
    model = TuiModel(clock=clock)
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="prompt"))
    backend = StatusBackend()
    coordinator = TuiRenderCoordinator(model, backend, status_refresh_interval=0.001)

    coordinator.flush_render()
    coordinator.sync_status_timer()
    clock.value = 2.0
    for _ in range(20):
        await asyncio.sleep(0.001)
        if any(" 02.0s" in "".join(span.text for span in line) for line in backend.statuses):
            break

    assert any(" 02.0s" in "".join(span.text for span in line) for line in backend.statuses)
    coordinator.stop_status_timer()
    await asyncio.sleep(0)


async def test_status_timer_stops_after_terminal_state_and_shutdown_cancels_it() -> None:
    clock = FakeClock()
    model = TuiModel(clock=clock)
    model.status.set_task_status("verifying", command="pytest")
    backend = StatusBackend()
    coordinator = TuiRenderCoordinator(model, backend, status_refresh_interval=0.001)

    coordinator.flush_render()
    coordinator.sync_status_timer()
    await asyncio.sleep(0)
    assert coordinator.status_task is not None

    model.status.set_task_status("verified")
    coordinator.sync_status_timer()
    await asyncio.sleep(0)
    assert coordinator.status_task is None
    status_count = len(backend.statuses)
    await asyncio.sleep(0.005)
    assert len(backend.statuses) == status_count

    model.status.set_task_status("verifying")
    coordinator.sync_status_timer()
    assert coordinator.status_task is not None
    coordinator.cancel_pending_render()
    await asyncio.sleep(0)
    assert coordinator.status_task is None
