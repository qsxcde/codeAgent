"""Contracts for creating a versioned Linux TUI benchmark baseline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _scenario(scenario: str) -> dict:
    return {
        "schema_version": 2,
        "scenario": scenario,
        "parameters": {
            "history_blocks": 100,
            "stream_chars": 10_000,
            "tool_output_bytes": 20_000,
            "width": 80,
            "height": 24,
        },
        "iterations": 3,
        "metrics": {"frame_total_ms": {"count": 3, "p50_ms": 1, "p95_ms": 2}},
        "counters": {"peak_memory_bytes": 100, "dropped_frames": 0, "over_budget_frames": 0},
        "environment": {"os": "Linux", "python_major_minor": "3.12", "commit": "abc"},
        "required_metrics": ["frame_total_ms"],
        "unavailable_metrics": {},
    }


def test_update_tui_baseline_combines_matching_linux_reports(tmp_path: Path) -> None:
    inputs = []
    for scenario in ("history", "stream", "tool-output", "restore"):
        path = tmp_path / f"{scenario}.json"
        path.write_text(json.dumps(_scenario(scenario)), encoding="utf-8")
        inputs.append(str(path))
    output = tmp_path / "baseline.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/update_tui_baseline.py",
            "--output",
            str(output),
            "--baseline-id",
            "linux-py312-tui-v2",
            *inputs,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["baseline_id"] == "linux-py312-tui-v2"
    assert set(payload["scenarios"]) == {"history", "stream", "tool-output", "restore"}
    assert payload["fixture"]["iterations"] == 3


def test_update_tui_baseline_rejects_non_linux_report(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    report = _scenario("history")
    report["environment"]["os"] = "Darwin"
    path.write_text(json.dumps(report), encoding="utf-8")
    output = tmp_path / "baseline.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/update_tui_baseline.py",
            "--output",
            str(output),
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Linux" in completed.stderr
