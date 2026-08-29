"""Deterministic pure-component inputs used by TUI performance benchmarks."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..presentation.blocks import AssistantBlock, ToolCallBlock, UserBlock
from ..presentation.primitives import RichLine
from ..rendering.coordinator import TuiEventBuffer, TuiRenderCoordinator
from ..state.model import TuiModel


_SCENARIOS = {"history", "stream", "tool-output", "restore", "scroll-resize"}
SCENARIO_REQUIRED_METRICS = {
    "history": ("frame_total_ms",),
    "stream": (
        "frame_total_ms",
        "submit_latency_ms",
        "first_token_latency_ms",
        "control_event_latency_ms",
    ),
    "tool-output": ("frame_total_ms",),
    "restore": ("frame_total_ms", "restore_ms"),
    "scroll-resize": ("frame_total_ms",),
}
STREAM_ONLY_METRICS = (
    "submit_latency_ms",
    "first_token_latency_ms",
    "control_event_latency_ms",
)


@dataclass(frozen=True)
class BenchmarkConfig:
    """Parameters shared by all offline benchmark scenarios."""

    scenario: str = "stream"
    history_blocks: int = 100
    stream_chars: int = 10_000
    tool_output_bytes: int = 20_000
    iterations: int = 5
    width: int = 80
    height: int = 24

    def __post_init__(self) -> None:
        if self.scenario not in _SCENARIOS:
            raise ValueError(f"unknown TUI benchmark scenario: {self.scenario}")
        for name in (
            "history_blocks",
            "stream_chars",
            "tool_output_bytes",
            "iterations",
            "width",
            "height",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.iterations == 0:
            raise ValueError("iterations must be positive")
        if self.width == 0 or self.height == 0:
            raise ValueError("width and height must be positive")


@dataclass(frozen=True)
class FixtureMessage:
    """Small history message compatible with TuiModel.hydrate_history."""

    role: str
    content: str
    tool_calls: tuple[dict[str, Any], ...] = ()
    tool_call_id: str | None = None


@dataclass
class FakeBackend:
    """Minimal backend used to measure view conversion without Textual."""

    width: int = 80
    height: int = 24
    frames: int = 0
    last_lines: list[RichLine] = field(default_factory=list)
    last_status: RichLine | None = None

    def transcript_size(self) -> tuple[int, int]:
        return self.width, self.height

    def render(self, lines: list[RichLine]) -> None:
        self.frames += 1
        self.last_lines = lines

    def set_status(self, line: RichLine) -> None:
        self.last_status = line

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


@dataclass
class TuiBenchmarkFixture:
    """Prepared pure-component inputs for one benchmark iteration."""

    model: TuiModel
    backend: FakeBackend
    stream_text: str
    tool_output: str
    restore_history: list[FixtureMessage]
    event_buffer: TuiEventBuffer
    coordinator: TuiRenderCoordinator


def build_fixture(
    config: BenchmarkConfig,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> TuiBenchmarkFixture:
    model = TuiModel(clock=clock)
    for index in range(config.history_blocks):
        _append_history_fixture_block(model, index)

    restore_history = [
        FixtureMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"history message {index}",
        )
        for index in range(config.history_blocks)
    ]
    backend = FakeBackend(config.width, config.height)
    return TuiBenchmarkFixture(
        model=model,
        backend=backend,
        stream_text="x" * config.stream_chars,
        tool_output="t" * config.tool_output_bytes,
        restore_history=restore_history,
        event_buffer=TuiEventBuffer(model.apply),
        coordinator=TuiRenderCoordinator(model, backend),
    )


def _append_history_fixture_block(model: TuiModel, index: int) -> None:
    """Append deterministic mixed-shape history for long-session measurements."""
    if index % 37 == 0:
        block = AssistantBlock()
        block.append_text("long assistant line " + "x" * 240 + "\n" + "tail")
        block.finalize()
        model.transcript.append(block)
    elif index % 17 == 0:
        model.transcript.append(AssistantBlock())
    elif index % 11 == 0:
        block = ToolCallBlock("fixture", {}, call_id=f"history-{index}")
        block.set_result(
            f"tool line {index}\nsecond line",
            output_metadata={
                "source": "structured",
                "completeness": "complete",
                "total_bytes": 32,
                "total_lines": 2,
                "shown_lines": 2,
                "exit_code": 0,
            },
        )
        model.transcript.append(block)
    elif index % 5 == 0:
        model.transcript.append(UserBlock(f"history user {index}\nsecond line"))
    elif index % 3 == 0:
        model.append_info(f"history block {index}\nsecond line")
    else:
        model.append_info(f"history block {index}")


def scenarios() -> tuple[str, ...]:
    return tuple(sorted(_SCENARIOS))
