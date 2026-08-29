#!/usr/bin/env python3
"""Compare two benchmark JSON files and report relative metric changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid benchmark payload: {path}")
    if not isinstance(payload.get("metrics"), dict) and not isinstance(payload.get("scenarios"), dict):
        raise ValueError(f"invalid benchmark payload: {path}")
    return payload


def _baseline_for_scenario(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    scenarios = baseline.get("scenarios")
    if scenarios is None:
        return baseline
    scenario = current.get("scenario")
    selected = scenarios.get(scenario)
    if not isinstance(selected, dict):
        raise ValueError(f"baseline has no scenario: {scenario}")
    return selected


def _compatibility_reason(current: dict[str, Any], baseline: dict[str, Any]) -> str | None:
    if current.get("schema_version", 1) != baseline.get("schema_version", 1):
        return "schema_version differs"
    if current.get("scenario") != baseline.get("scenario"):
        return "scenario differs"
    if current.get("parameters") != baseline.get("parameters"):
        return "parameters differ"
    current_env = current.get("environment", {})
    baseline_env = baseline.get("environment", {})
    for key in ("os", "python_major_minor"):
        current_value = current_env.get(key)
        baseline_value = baseline_env.get(key)
        if current_value is not None and baseline_value is not None and current_value != baseline_value:
            return f"environment.{key} differs"
    current_viewport = current.get("environment", {}).get("viewport")
    baseline_viewport = baseline.get("environment", {}).get("viewport")
    if current_viewport is not None and baseline_viewport is not None and current_viewport != baseline_viewport:
        return "environment.viewport differs"
    return None


def _missing_required_metrics(document: dict[str, Any]) -> list[str]:
    required = document.get("required_metrics", [])
    if not isinstance(required, list):
        return ["required_metrics"]
    metrics = document.get("metrics", {})
    unavailable = document.get("unavailable_metrics", {})
    if not isinstance(metrics, dict) or not isinstance(unavailable, dict):
        return ["metrics"]
    return sorted(
        name
        for name in required
        if isinstance(name, str)
        and name not in metrics
        and unavailable.get(name) != "not_applicable"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path)
    parser.add_argument("baseline", type=Path, nargs="?")
    parser.add_argument("--max-regression", type=float, default=0.20)
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="return non-zero when a metric exceeds --max-regression",
    )
    return parser


def _comparison(current: dict[str, Any], baseline: dict[str, Any], limit: float) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    current_metrics = current["metrics"]
    baseline_metrics = baseline["metrics"]
    for name in sorted(set(current_metrics) & set(baseline_metrics)):
        current_summary = current_metrics[name]
        baseline_summary = baseline_metrics[name]
        if not isinstance(current_summary, dict) or not isinstance(baseline_summary, dict):
            continue
        for field in ("p50_ms", "p95_ms"):
            old = baseline_summary.get(field)
            new = current_summary.get(field)
            if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old == 0:
                continue
            relative_change = (new - old) / old
            changes.append(
                {
                    "metric": name,
                    "statistic": field,
                    "baseline": old,
                    "current": new,
                    "relative_change": round(relative_change, 6),
                    "regression": relative_change > limit,
                }
            )
    current_counters = current.get("counters", {})
    baseline_counters = baseline.get("counters", {})
    for name in ("peak_memory_bytes",):
        old = baseline_counters.get(name)
        new = current_counters.get(name)
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old == 0:
            continue
        relative_change = (new - old) / old
        changes.append(
            {
                "metric": name,
                "statistic": "value",
                "baseline": old,
                "current": new,
                "relative_change": round(relative_change, 6),
                "regression": relative_change > limit,
            }
        )
    for name in ("dropped_frames", "over_budget_frames"):
        old = baseline_counters.get(name)
        new = current_counters.get(name)
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
            continue
        changes.append(
            {
                "metric": name,
                "statistic": "value",
                "baseline": old,
                "current": new,
                "relative_change": None,
                "regression": new > old,
            }
        )
    return changes


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    current = _load(args.current)
    if args.baseline is None:
        result = {
            "status": "no-baseline",
            "scenario": current.get("scenario"),
            "warning": "no baseline supplied; report is informational",
            "current": current,
            "comparisons": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    baseline_document = _load(args.baseline)
    try:
        baseline = _baseline_for_scenario(current, baseline_document)
    except ValueError as exc:
        result = {
            "status": "incomparable",
            "scenario": current.get("scenario"),
            "reason": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    reason = _compatibility_reason(current, baseline)
    if reason is not None:
        result = {
            "status": "incomparable",
            "scenario": current.get("scenario"),
            "reason": reason,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    missing_metrics = sorted(
        set(_missing_required_metrics(current)) | set(_missing_required_metrics(baseline))
    )
    if missing_metrics:
        result = {
            "status": "incomplete",
            "scenario": current.get("scenario"),
            "missing_metrics": missing_metrics,
            "warning": "required benchmark metrics were not measured",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    comparisons = _comparison(current, baseline, args.max_regression)
    regressions = [item for item in comparisons if item["regression"]]
    result = {
        "status": "regression" if regressions else "passed",
        "scenario": current.get("scenario"),
        "max_regression": args.max_regression,
        "baseline": {
            "id": baseline_document.get("baseline_id"),
            "scenario": baseline.get("scenario"),
            "environment": baseline.get("environment"),
        },
        "current": {"scenario": current.get("scenario"), "environment": current.get("environment")},
        "comparisons": comparisons,
        "regressions": regressions,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if regressions and args.fail_on_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())
