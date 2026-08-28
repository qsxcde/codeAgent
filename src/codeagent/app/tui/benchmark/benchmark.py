"""Offline, deterministic TUI benchmark scenarios."""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codeagent.core.events import AgentEvent, EventType

from ..state.model import TuiModel
from ..presentation.primitives import RichLine
from ..presentation.md_renderer import md_renderer
from .performance import BenchmarkResult, PerformanceRecorder


_SCENARIOS = {"history", "stream", "tool-output", "restore", "scroll-resize"}


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

    def transcript_size(self) -> tuple[int, int]:
        return self.width, self.height

    def render(self, lines: list[RichLine]) -> None:
        self.frames += 1
        self.last_lines = lines

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


def build_fixture(config: BenchmarkConfig) -> TuiBenchmarkFixture:
    model = TuiModel()
    for index in range(config.history_blocks):
        model.append_info(f"history block {index}")

    restore_history = [
        FixtureMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"history message {index}",
        )
        for index in range(config.history_blocks)
    ]
    return TuiBenchmarkFixture(
        model=model,
        backend=FakeBackend(config.width, config.height),
        stream_text="x" * config.stream_chars,
        tool_output="t" * config.tool_output_bytes,
        restore_history=restore_history,
    )


def environment_metadata() -> dict[str, str]:
    """Return safe environment metadata without reading application data."""
    metadata = {
        "python": sys.version.split()[0],
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "os": platform.system(),
        "platform": platform.platform(),
    }
    try:
        root = Path(__file__).resolve().parents[4]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    metadata["commit"] = commit or "unknown"
    return metadata


def _render_frame(
    fixture: TuiBenchmarkFixture, recorder: PerformanceRecorder, config: BenchmarkConfig
) -> None:
    with recorder.measure("frame_total_ms"):
        with recorder.measure("model_render_ms"):
            lines = fixture.model.render(*fixture.backend.transcript_size())
        with recorder.measure("backend_render_ms"):
            fixture.backend.render(lines)


def _stream_chunks(text: str, chunk_size: int = 256) -> list[str]:
    return [text[start : start + chunk_size] for start in range(0, len(text), chunk_size)]


def _run_scenario(
    config: BenchmarkConfig,
    fixture: TuiBenchmarkFixture,
    recorder: PerformanceRecorder,
) -> None:
    if config.scenario == "history":
        _render_frame(fixture, recorder, config)
    elif config.scenario == "stream":
        fixture.model.apply(AgentEvent(EventType.SESSION_STARTED, "prompt"))
        for chunk in _stream_chunks(fixture.stream_text):
            with recorder.measure("event_apply_ms"):
                fixture.model.apply(AgentEvent(EventType.TEXT_DELTA, chunk))
            _render_frame(fixture, recorder, config)
        with recorder.measure("markdown_render_ms"):
            md_renderer(fixture.stream_text, max(1, config.width - 2))
    elif config.scenario == "tool-output":
        fixture.model.apply(
            AgentEvent(
                EventType.TOOL_CALL,
                [{"name": "fixture", "args": {}, "id": "fixture-call"}],
            )
        )
        fixture.model.apply(
            AgentEvent(
                EventType.TOOL_RESULT,
                fixture.tool_output,
                metadata={"tool_call_id": "fixture-call"},
            )
        )
        _render_frame(fixture, recorder, config)
    elif config.scenario == "restore":
        with recorder.measure("restore_ms"):
            fixture.model.hydrate_history(fixture.restore_history)
        _render_frame(fixture, recorder, config)
    else:
        fixture.model.transcript.scroll(config.height // 2)
        fixture.backend.resize(config.width + 1, config.height)
        _render_frame(fixture, recorder, config)
        fixture.backend.resize(config.width, config.height)
        _render_frame(fixture, recorder, config)


def run_benchmark(config: BenchmarkConfig) -> BenchmarkResult:
    """Run one deterministic scenario and return metrics without payload data."""
    recorder = PerformanceRecorder()
    last_snapshot: dict[str, int | float] = {}

    for _ in range(config.iterations):
        fixture = build_fixture(config)
        _run_scenario(config, fixture, recorder)
        last_snapshot = fixture.model.performance_snapshot()

    memory_recorder = PerformanceRecorder()
    with memory_recorder.measure_memory():
        memory_fixture = build_fixture(config)
        _run_scenario(config, memory_fixture, PerformanceRecorder())

    counters = recorder.counters()
    counters.update(last_snapshot)
    counters.update(memory_recorder.counters())
    frames = int(counters.get("frames", 0))
    events = int(counters.get("event_count", 0))
    counters["events_per_frame"] = round(events / frames, 3) if frames else 0.0
    return BenchmarkResult(
        scenario=config.scenario,
        parameters={
            "history_blocks": config.history_blocks,
            "stream_chars": config.stream_chars,
            "tool_output_bytes": config.tool_output_bytes,
            "width": config.width,
            "height": config.height,
        },
        iterations=config.iterations,
        metrics=recorder.summaries(),
        counters=counters,
        environment=environment_metadata(),
    )


def scenarios() -> tuple[str, ...]:
    return tuple(sorted(_SCENARIOS))
