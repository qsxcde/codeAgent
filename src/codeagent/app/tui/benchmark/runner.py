"""Scenario execution for deterministic TUI performance fixtures."""

from __future__ import annotations

from codeagent.core.contracts.events import AgentEvent, EventType

from ..presentation.md_renderer import md_renderer
from .fixture import BenchmarkConfig, TuiBenchmarkFixture
from .performance import PerformanceRecorder


def _render_frame(fixture: TuiBenchmarkFixture, recorder: PerformanceRecorder) -> None:
    with recorder.measure("frame_total_ms"):
        fixture.coordinator.flush_render()
    recorder.record_sample("model_render_ms", fixture.model.render_stats["last_render_ms"])


def _stream_chunks(text: str, chunk_size: int = 256) -> list[str]:
    return [text[start : start + chunk_size] for start in range(0, len(text), chunk_size)]


def run_scenario(
    config: BenchmarkConfig,
    fixture: TuiBenchmarkFixture,
    recorder: PerformanceRecorder,
) -> None:
    """Run one scenario without recording user-visible fixture content."""
    if config.scenario == "history":
        _render_frame(fixture, recorder)
    elif config.scenario == "stream":
        _run_stream(config, fixture, recorder)
    elif config.scenario == "tool-output":
        _run_tool_output(fixture, recorder)
    elif config.scenario == "restore":
        with recorder.measure("restore_ms"):
            fixture.model.hydrate_history(fixture.restore_history)
        _render_frame(fixture, recorder)
    else:
        fixture.model.transcript.scroll(config.height // 2)
        fixture.backend.resize(config.width + 1, config.height)
        _render_frame(fixture, recorder)
        fixture.backend.resize(config.width, config.height)
        _render_frame(fixture, recorder)


def _run_stream(
    config: BenchmarkConfig,
    fixture: TuiBenchmarkFixture,
    recorder: PerformanceRecorder,
) -> None:
    recorder.mark("submit")
    fixture.model.append_pending_user("fixture prompt")
    _render_frame(fixture, recorder)
    recorder.mark("submit_ready_frame")
    recorder.record_latency("submit_latency_ms", "submit", "submit_ready_frame")
    fixture.event_buffer.push(AgentEvent(EventType.SESSION_STARTED, "prompt"))
    fixture.event_buffer.flush()
    first_token_seen = False
    for chunk in _stream_chunks(fixture.stream_text):
        with recorder.measure("event_apply_ms"), recorder.measure("control_event_latency_ms"):
            fixture.event_buffer.push(AgentEvent(EventType.TEXT_DELTA, chunk))
            fixture.event_buffer.flush()
        _render_frame(fixture, recorder)
        if not first_token_seen and chunk:
            recorder.mark("first_token_visible")
            recorder.record_latency(
                "first_token_latency_ms", "submit", "first_token_visible"
            )
            first_token_seen = True
    with recorder.measure("markdown_render_ms"):
        md_renderer(fixture.stream_text, max(1, config.width - 2))


def _run_tool_output(fixture: TuiBenchmarkFixture, recorder: PerformanceRecorder) -> None:
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
    _render_frame(fixture, recorder)
