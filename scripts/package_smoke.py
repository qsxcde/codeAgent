#!/usr/bin/env python3
"""Validate an installed wheel without contacting a real model provider."""

from __future__ import annotations

import importlib.resources
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import argparse


REQUIRED_RESOURCES = (
    "prompts/system.md",
    "skills/commit-message/SKILL.md",
    "skills/dependency-audit/SKILL.md",
)


def _console_script() -> Path:
    executable_name = "codeagent.exe" if os.name == "nt" else "codeagent"
    executable = Path(sys.executable).with_name(executable_name)
    if not executable.is_file():
        raise RuntimeError(f"installed console script not found: {executable}")
    return executable


def _check_resources() -> list[str]:
    root = importlib.resources.files("codeagent.resources")
    missing = [name for name in REQUIRED_RESOURCES if not root.joinpath(*name.split("/")).is_file()]
    if missing:
        raise RuntimeError(f"installed resources missing: {', '.join(missing)}")
    return list(REQUIRED_RESOURCES)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the smoke result JSON to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    resources = _check_resources()
    executable = _console_script()
    with tempfile.TemporaryDirectory(prefix="codeagent-package-smoke-") as config_dir:
        environment = os.environ.copy()
        environment.update(
            {
                "LLM_PROVIDER": "fake",
                "HOME": config_dir,
                "USERPROFILE": config_dir,
            }
        )
        environment.pop("DEEPSEEK_API_KEY", None)
        environment.pop("OPENAI_API_KEY", None)
        completed = subprocess.run(
            [str(executable), "--prompt", "你好"],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=30,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"installed CLI failed with exit code {completed.returncode}: {completed.stderr[-2000:]}"
        )
    if "测试回复" not in completed.stdout:
        raise RuntimeError("installed CLI did not return the fake provider response")
    payload = {
        "schema_version": 1,
        "status": "passed",
        "python": sys.version.split()[0],
        "resources": resources,
        "cli_returncode": completed.returncode,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
