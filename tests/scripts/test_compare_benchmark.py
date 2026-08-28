"""CLI contracts for comparable and regression benchmark reports."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PARAMETERS = {
    "history_blocks": 100,
    "stream_chars": 10_000,
    "tool_output_bytes": 20_000,
    "width": 80,
    "height": 24,
}
ENVIRONMENT = {"os": "Linux", "python": "3.12"}


def _payload(*, p95_ms: float = 10.0, peak_memory_bytes: int = 100) -> dict:
    return {
        "schema_version": 1,
        "scenario": "stream",
        "parameters": PARAMETERS,
        "iterations": 3,
        "metrics": {
            "frame_total_ms": {
                "count": 3,
                "minimum_ms": 5.0,
                "maximum_ms": p95_ms,
                "p50_ms": 8.0,
                "p95_ms": p95_ms,
            }
        },
        "counters": {"peak_memory_bytes": peak_memory_bytes},
        "environment": ENVIRONMENT,
    }


def _run_compare(tmp_path: Path, current: dict, baseline: dict, *extra: str) -> subprocess.CompletedProcess[str]:
    current_path = tmp_path / "current.json"
    baseline_path = tmp_path / "baseline.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "scripts/compare_benchmark.py",
            str(current_path),
            str(baseline_path),
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_compare_benchmark_reads_combined_baseline(tmp_path: Path) -> None:
    current = _payload()
    baseline = {
        "schema_version": 1,
        "baseline_id": "linux-py312-tui-v1",
        "scenarios": {"stream": _payload()},
    }

    completed = _run_compare(tmp_path, current, baseline)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "passed"
    assert result["scenario"] == "stream"


def test_compare_benchmark_marks_fixture_mismatch_incomparable(tmp_path: Path) -> None:
    current = _payload()
    baseline_payload = _payload()
    baseline_payload["parameters"] = {**PARAMETERS, "stream_chars": 999}
    baseline = {"schema_version": 1, "scenarios": {"stream": baseline_payload}}

    completed = _run_compare(tmp_path, current, baseline)

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["status"] == "incomparable"
    assert "parameters" in result["reason"]


def test_compare_benchmark_can_fail_on_memory_regression(tmp_path: Path) -> None:
    current = _payload(p95_ms=10.0, peak_memory_bytes=130)
    baseline = {"schema_version": 1, "scenarios": {"stream": _payload()}}

    completed = _run_compare(tmp_path, current, baseline, "--fail-on-regression")

    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["status"] == "regression"
    assert any(item["metric"] == "peak_memory_bytes" for item in result["regressions"])
