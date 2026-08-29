#!/usr/bin/env python3
"""Create a versioned TUI baseline from matching Linux benchmark reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
REQUIRED_SCENARIOS = ("history", "restore", "stream", "tool-output")


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid benchmark report: {path}")
    return payload


def _missing_required_metrics(report: dict[str, Any]) -> list[str]:
    required = report.get("required_metrics", [])
    metrics = report.get("metrics", {})
    unavailable = report.get("unavailable_metrics", {})
    if (
        not isinstance(required, list)
        or not isinstance(metrics, dict)
        or not isinstance(unavailable, dict)
    ):
        return ["metric_contract"]
    return sorted(
        name
        for name in required
        if isinstance(name, str)
        and name not in metrics
        and unavailable.get(name) != "not_applicable"
    )


def _validate(reports: list[dict[str, Any]]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if not reports:
        raise ValueError(f"exactly one report is required for each scenario: {REQUIRED_SCENARIOS}")
    scenarios: dict[str, Any] = {}
    first_parameters: dict[str, Any] | None = None
    first_environment: dict[str, Any] | None = None
    first_commit: str | None = None
    for report in reports:
        scenario = report.get("scenario")
        if scenario not in REQUIRED_SCENARIOS or scenario in scenarios:
            raise ValueError(
                "reports must contain one of each required scenario, "
                f"got {scenario!r}"
            )
        if report.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"{scenario}: schema_version must be {SCHEMA_VERSION}")
        environment = report.get("environment")
        if not isinstance(environment, dict):
            raise ValueError(f"{scenario}: environment is missing")
        if environment.get("os") != "Linux":
            raise ValueError(f"{scenario}: baseline reports must run on Linux")
        if environment.get("python_major_minor") != "3.12":
            raise ValueError(f"{scenario}: baseline reports must run on Python 3.12")
        missing = _missing_required_metrics(report)
        if missing:
            raise ValueError(f"{scenario}: required metrics are missing: {', '.join(missing)}")
        parameters = report.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"{scenario}: parameters are missing")
        commit = str(environment.get("commit") or "unknown")
        if first_parameters is None:
            first_parameters = dict(parameters)
            first_environment = dict(environment)
            first_commit = commit
        elif parameters != first_parameters:
            raise ValueError(f"{scenario}: fixture parameters differ")
        elif commit != first_commit:
            raise ValueError(f"{scenario}: report commits differ")
        scenarios[scenario] = report
    if set(scenarios) != set(REQUIRED_SCENARIOS):
        if len(reports) != len(REQUIRED_SCENARIOS):
            raise ValueError(
                f"exactly one report is required for each scenario: {REQUIRED_SCENARIOS}"
            )
        missing_scenarios = sorted(set(REQUIRED_SCENARIOS) - set(scenarios))
        raise ValueError(f"missing scenarios: {', '.join(missing_scenarios)}")
    assert first_parameters is not None
    assert first_environment is not None
    assert first_commit is not None
    return first_commit, first_parameters, {
        "environment": first_environment,
        "scenarios": scenarios,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-id", default="linux-py312-tui-v2")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        reports = [_load(path) for path in args.reports]
        commit, parameters, validated = _validate(reports)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        _parser().error(str(exc))
    environment = validated["environment"]
    baseline = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": args.baseline_id,
        "commit": commit,
        "environment": {
            "os": environment["os"],
            "python_major_minor": environment["python_major_minor"],
            "platform": environment.get("platform", "unknown"),
            "viewport": {
                "width": parameters["width"],
                "height": parameters["height"],
            },
        },
        "fixture": {
            **parameters,
            "iterations": reports[0]["iterations"],
        },
        "scenarios": validated["scenarios"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
