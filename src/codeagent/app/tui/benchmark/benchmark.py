"""Offline, deterministic TUI benchmark reporting."""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .fixture import (
    SCENARIO_REQUIRED_METRICS,
    STREAM_ONLY_METRICS,
    BenchmarkConfig,
    FixtureMessage,
    FakeBackend,
    TuiBenchmarkFixture,
    build_fixture,
    scenarios,
)
from .performance import BenchmarkResult, PerformanceRecorder
from .runner import run_scenario

__all__ = [
    "BenchmarkConfig",
    "BenchmarkResult",
    "FixtureMessage",
    "FakeBackend",
    "TuiBenchmarkFixture",
    "build_fixture",
    "run_benchmark",
    "scenarios",
]


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


def run_benchmark(
    config: BenchmarkConfig,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> BenchmarkResult:
    """Run one deterministic scenario and return metrics without payload data."""
    recorder = PerformanceRecorder(clock=clock)
    last_snapshot: dict[str, int | float] = {}

    for _ in range(config.iterations):
        fixture = build_fixture(config, clock=clock)
        run_scenario(config, fixture, recorder)
        last_snapshot = fixture.model.performance_snapshot()
        last_snapshot.update(fixture.coordinator.performance_snapshot())
        last_snapshot.update(
            {
                "event_buffer_flushes": fixture.event_buffer.flush_count,
                "max_pending_chars": fixture.event_buffer.max_pending_chars,
            }
        )

    memory_recorder = PerformanceRecorder(clock=clock)
    with memory_recorder.measure_memory():
        memory_fixture = build_fixture(config, clock=clock)
        run_scenario(config, memory_fixture, PerformanceRecorder(clock=clock))

    counters = recorder.counters()
    counters.update(last_snapshot)
    counters.update(memory_recorder.counters())
    frames = int(counters.get("frames", 0))
    events = int(counters.get("event_count", 0))
    counters["events_per_frame"] = round(events / frames, 3) if frames else 0.0
    metrics = recorder.summaries()
    control = metrics.get("control_event_latency_ms")
    if control is not None:
        counters["control_event_p95_ms"] = control.p95_ms
    required_metrics = SCENARIO_REQUIRED_METRICS[config.scenario]
    unavailable_metrics = {
        name: "not_applicable"
        for name in STREAM_ONLY_METRICS
        if name not in required_metrics
    }
    unavailable_metrics.update(
        {
            name: "not_measured"
            for name in required_metrics
            if name not in metrics
        }
    )
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
        metrics=metrics,
        counters=counters,
        environment=environment_metadata(),
        required_metrics=required_metrics,
        unavailable_metrics=unavailable_metrics,
    )
