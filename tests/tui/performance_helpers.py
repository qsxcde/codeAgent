"""稳定的 TUI 性能与事件完整性断言,不接触用户内容。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from codeagent.app.tui.benchmark.performance import MetricSummary


def assert_control_latency(samples_ms: Iterable[float]) -> None:
    """Assert the v4-18 p95/max control-event budget in milliseconds."""
    summary = MetricSummary.from_samples(list(samples_ms))
    assert summary.p95_ms <= 50.0
    assert summary.maximum_ms <= 100.0


def assert_frame_budget(samples_ms: Iterable[float], budget_ms: float = 33.0) -> None:
    """Assert that measured frame work stays within the configured budget."""
    summary = MetricSummary.from_samples(list(samples_ms))
    assert summary.maximum_ms <= budget_ms


def assert_event_order(actual: Sequence[str], expected: Sequence[str]) -> None:
    """Assert that structural events preserve their relative order."""
    positions = [actual.index(event) for event in expected]
    assert positions == sorted(positions)


def assert_text_complete(actual: str, expected: str) -> None:
    """Assert exact text preservation without logging either content value."""
    assert actual == expected
