"""Offline contracts for TUI performance measurements."""

import json
import subprocess
import sys

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.app.tui.benchmark.performance import (
    BenchmarkResult,
    MetricSummary,
    PerformanceRecorder,
)
from codeagent.app.tui.state.model import TuiModel
from codeagent.app.tui.benchmark.benchmark import BenchmarkConfig, build_fixture, run_benchmark


def test_metric_summary_reports_nearest_rank_percentiles() -> None:
    summary = MetricSummary.from_samples([1.0, 2.0, 3.0, 4.0])

    assert summary.count == 4
    assert summary.p50_ms == 2.0
    assert summary.p95_ms == 4.0


def test_benchmark_result_serializes_metrics_and_safe_metadata() -> None:
    result = BenchmarkResult(
        scenario="render-history",
        parameters={"blocks": 10},
        iterations=2,
        metrics={"model_render_ms": MetricSummary.from_samples([1.0, 2.0])},
        counters={"event_count": 4},
        environment={"python": "3.12"},
    )

    payload = json.loads(result.to_json())

    assert payload["schema_version"] == 1
    assert payload["scenario"] == "render-history"
    assert payload["metrics"]["model_render_ms"]["p50_ms"] == 1.0
    assert payload["counters"] == {"event_count": 4}
    assert "prompt" not in result.to_json().lower()


def test_performance_recorder_uses_injected_clock() -> None:
    ticks = iter([10.0, 10.125])
    recorder = PerformanceRecorder(clock=lambda: next(ticks))

    with recorder.measure("render"):
        pass

    assert recorder.samples("render") == [125.0]


def test_performance_recorder_collects_counters_and_peak_memory() -> None:
    recorder = PerformanceRecorder()
    recorder.increment("event_count", 3)

    with recorder.measure_memory():
        payload = bytearray(4096)
        payload[0] = 1

    assert recorder.counters()["event_count"] == 3
    assert recorder.counters()["peak_memory_bytes"] > 0


def test_tui_model_exposes_safe_render_snapshot() -> None:
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, "hello"))
    model.render(80, 5)

    snapshot = model.performance_snapshot()

    assert snapshot["event_count"] == 1
    assert snapshot["block_count"] == 1
    assert snapshot["visible_rows"] > 0
    assert snapshot["cache_entries"] >= 1
    assert "hello" not in snapshot


def test_benchmark_fixture_builds_history_and_streaming_inputs() -> None:
    fixture = build_fixture(
        BenchmarkConfig(
            scenario="stream",
            history_blocks=10,
            stream_chars=12,
            tool_output_bytes=32,
        )
    )

    assert len(fixture.model.transcript.blocks) == 10
    assert fixture.stream_text == "x" * 12
    assert fixture.tool_output == "t" * 32
    assert fixture.backend.transcript_size() == (80, 24)


def test_benchmark_fixture_can_prepare_restore_history() -> None:
    fixture = build_fixture(
        BenchmarkConfig(scenario="restore", history_blocks=3, stream_chars=0)
    )

    assert len(fixture.restore_history) == 3
    assert [message.role for message in fixture.restore_history] == [
        "user",
        "assistant",
        "user",
    ]


def test_benchmark_command_writes_json_result(tmp_path) -> None:
    output = tmp_path / "tui-baseline.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_tui.py",
            "--scenario",
            "history",
            "--blocks",
            "3",
            "--iterations",
            "1",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scenario"] == "history"
    assert payload["parameters"]["history_blocks"] == 3


def test_run_benchmark_reports_render_metrics() -> None:
    result = run_benchmark(
        BenchmarkConfig(scenario="history", history_blocks=3, iterations=1)
    )

    assert "model_render_ms" in result.metrics
    assert result.counters["block_count"] == 3
    assert result.counters["peak_memory_bytes"] > 0
    assert result.environment["os"]


def test_benchmark_fixture_rendering_is_deterministic() -> None:
    first = build_fixture(BenchmarkConfig(scenario="history", history_blocks=10))
    second = build_fixture(BenchmarkConfig(scenario="history", history_blocks=10))

    first.model.render(*first.backend.transcript_size())
    second.model.render(*second.backend.transcript_size())

    assert first.model.performance_snapshot() == second.model.performance_snapshot()


def test_long_history_only_materializes_a_bounded_view() -> None:
    result = run_benchmark(
        BenchmarkConfig(scenario="history", history_blocks=1_000, iterations=1)
    )

    assert result.counters["block_count"] == 1_000
    assert result.counters["cache_entries"] < result.counters["block_count"]
    assert result.counters["visible_rows"] <= 24
