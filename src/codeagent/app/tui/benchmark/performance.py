"""Development-only measurement primitives for the TUI.

The module deliberately contains no terminal, model, or session dependencies.
It records timings and counters only; callers decide which scenarios to run
and which metadata is safe to persist.
"""

from __future__ import annotations

import json
import math
import tracemalloc
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


BENCHMARK_SCHEMA_VERSION = 2


def _nearest_rank(values: list[float], percentile: float) -> float:
    """Return a deterministic nearest-rank percentile from sorted values."""
    if not values:
        raise ValueError("percentile requires at least one sample")
    rank = max(1, math.ceil(percentile / 100 * len(values)))
    return values[min(len(values), rank) - 1]


@dataclass(frozen=True)
class MetricSummary:
    """Summary statistics for one timing metric, expressed in milliseconds."""

    count: int
    minimum_ms: float
    maximum_ms: float
    p50_ms: float
    p95_ms: float

    @classmethod
    def from_samples(cls, samples: list[float] | tuple[float, ...]) -> "MetricSummary":
        if not samples:
            raise ValueError("metric summary requires at least one sample")
        values = sorted(float(value) for value in samples)
        return cls(
            count=len(values),
            minimum_ms=values[0],
            maximum_ms=values[-1],
            p50_ms=_nearest_rank(values, 50),
            p95_ms=_nearest_rank(values, 95),
        )

    def to_dict(self) -> dict[str, int | float]:
        return {
            "count": self.count,
            "minimum_ms": self.minimum_ms,
            "maximum_ms": self.maximum_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
        }


@dataclass(frozen=True)
class BenchmarkResult:
    """Serializable result for one benchmark scenario."""

    scenario: str
    parameters: dict[str, Any]
    iterations: int
    metrics: dict[str, MetricSummary]
    counters: dict[str, int | float]
    environment: dict[str, str]
    schema_version: int = BENCHMARK_SCHEMA_VERSION
    required_metrics: tuple[str, ...] = ()
    unavailable_metrics: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scenario": self.scenario,
            "parameters": dict(self.parameters),
            "iterations": self.iterations,
            "metrics": {
                name: summary.to_dict() for name, summary in self.metrics.items()
            },
            "counters": dict(self.counters),
            "environment": dict(self.environment),
            "required_metrics": list(self.required_metrics),
            "unavailable_metrics": dict(self.unavailable_metrics),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


class PerformanceRecorder:
    """Collect timing samples and counters with an injectable monotonic clock."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._samples: dict[str, list[float]] = {}
        self._counters: dict[str, int | float] = {}
        self._marks: dict[str, float] = {}

    def mark(self, name: str) -> None:
        """Record an event boundary without retaining event or user content."""
        self._marks[name] = self._clock()

    def record_latency(self, name: str, start: str, end: str) -> None:
        """Record the elapsed time between two previously marked boundaries."""
        try:
            started = self._marks[start]
            finished = self._marks[end]
        except KeyError as exc:
            raise ValueError(f"missing performance mark: {exc.args[0]}") from exc
        elapsed_ms = (finished - started) * 1000
        if elapsed_ms < 0:
            raise ValueError("performance marks must be monotonic")
        self._samples.setdefault(name, []).append(round(elapsed_ms, 6))

    def record_sample(self, name: str, value_ms: float) -> None:
        """Add an already measured millisecond sample to a metric."""
        value = float(value_ms)
        if value < 0 or not math.isfinite(value):
            raise ValueError("performance samples must be finite and non-negative")
        self._samples.setdefault(name, []).append(round(value, 6))

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = self._clock()
        try:
            yield
        finally:
            elapsed_ms = (self._clock() - started) * 1000
            self._samples.setdefault(name, []).append(round(elapsed_ms, 6))

    def increment(self, name: str, value: int | float = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def set_counter(self, name: str, value: int | float) -> None:
        self._counters[name] = value

    def samples(self, name: str) -> list[float]:
        return list(self._samples.get(name, []))

    def summaries(self) -> dict[str, MetricSummary]:
        return {
            name: MetricSummary.from_samples(values)
            for name, values in self._samples.items()
            if values
        }

    def counters(self) -> dict[str, int | float]:
        return dict(self._counters)

    @contextmanager
    def measure_memory(self) -> Iterator[None]:
        """Record the peak Python allocation observed during a measured block."""
        owns_tracing = not tracemalloc.is_tracing()
        if owns_tracing:
            tracemalloc.start()
        tracemalloc.reset_peak()
        try:
            yield
        finally:
            _current, peak = tracemalloc.get_traced_memory()
            self._counters["peak_memory_bytes"] = max(
                self._counters.get("peak_memory_bytes", 0), peak
            )
            if owns_tracing:
                tracemalloc.stop()
