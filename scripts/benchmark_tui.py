#!/usr/bin/env python3
"""Run an offline TUI benchmark and print or persist its JSON result."""

from __future__ import annotations

import argparse
from pathlib import Path

from codeagent.app.tui.benchmark.benchmark import BenchmarkConfig, run_benchmark, scenarios


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=scenarios(), default="stream")
    parser.add_argument("--blocks", type=int, default=100)
    parser.add_argument("--stream-chars", type=int, default=10_000)
    parser.add_argument("--tool-output-bytes", type=int, default=20_000)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--width", type=int, default=80)
    parser.add_argument("--height", type=int, default=24)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON to this path instead of only printing it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_benchmark(
            BenchmarkConfig(
                scenario=args.scenario,
                history_blocks=args.blocks,
                stream_chars=args.stream_chars,
                tool_output_bytes=args.tool_output_bytes,
                iterations=args.iterations,
                width=args.width,
                height=args.height,
            )
        )
    except ValueError as exc:
        _parser().error(str(exc))

    payload = result.to_json()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
