"""可选外部检索器的安全进程边界。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from codeagent.tools.shared import ToolResourceLimits

__all__ = ["ExternalSearchResult", "run_optional_search", "run_rg"]


@dataclass(frozen=True)
class ExternalSearchResult:
    """一次成功外部检索的有界 stdout 预览。"""

    stdout: bytes
    truncated: bool = False


def run_optional_search(
    name: str,
    args: list[str],
    cwd: str | Path,
    *,
    timeout: float,
    max_output_bytes: int,
    cleanup_timeout: float,
) -> ExternalSearchResult | None:
    """尝试运行可选检索器；任何不可靠结果都返回 ``None`` 供调用方回退。"""
    executable = shutil.which(name)
    if not executable or max_output_bytes < 1:
        return None

    fd, output_name = tempfile.mkstemp(prefix="codeagent-search-")
    os.close(fd)
    output_path = Path(output_name)
    process: subprocess.Popen[bytes] | None = None
    try:
        try:
            with output_path.open("wb") as output:
                process = subprocess.Popen(
                    [executable, *args],
                    cwd=str(cwd),
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                )
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if process is None or not _terminate(process, cleanup_timeout):
                return None
            return None
        except OSError:
            return None

        if process.returncode not in (0, 1):
            return None
        with output_path.open("rb") as output:
            raw = output.read(max_output_bytes + 1)
        return ExternalSearchResult(
            raw[:max_output_bytes], truncated=len(raw) > max_output_bytes
        )
    except OSError:
        return None
    finally:
        output_path.unlink(missing_ok=True)


def _terminate(process: subprocess.Popen[bytes], timeout: float) -> bool:
    """终止超时的可选命令，并在有限等待内确认收尾。"""
    try:
        process.kill()
        process.wait(timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def run_rg(
    target: Path,
    pattern: str,
    glob: str | None,
    ignore_case: bool,
    literal: bool,
    context: int,
    limit: int,
    limits: ToolResourceLimits,
) -> tuple[list[str], bool] | None:
    """使用 rg 加速；任何不完整或不可解析结果均交给 Python fallback。"""
    args = [
        "--json",
        "--color",
        "never",
        "--no-heading",
        "--hidden",
        "--no-ignore",
    ]
    for noise in (".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"):
        args.extend(["--glob", f"!{noise}/**"])
    if glob:
        args.extend(["--glob", glob])
    if ignore_case:
        args.append("--ignore-case")
    if literal:
        args.append("--fixed-strings")
    if context:
        args.extend(["-C", str(context)])
    run_cwd, target_arg = _rg_target(target)
    args.extend(["--", pattern, target_arg])
    result = run_optional_search(
        "rg",
        args,
        run_cwd,
        timeout=_search_timeout(limits),
        max_output_bytes=limits.effective_output_bytes,
        cleanup_timeout=limits.cleanup_timeout,
    )
    if result is None or result.truncated:
        return None
    try:
        records = _parse_rg_records(result.stdout, target, run_cwd)
    except (UnicodeDecodeError, KeyError, TypeError, ValueError):
        return None
    matches = [record for record in records if record[0] == "match"]
    selected = matches[:limit]
    selected_keys = {(item[1], item[2]) for item in selected}
    lines: list[str] = []
    seen: set[tuple[str, int, str]] = set()
    for kind, rel, line_number, text in records:
        if kind == "match":
            if (rel, line_number) not in selected_keys:
                continue
            marker = ":"
        elif any(
            path == rel and abs(line_number - selected_line) <= context
            for path, selected_line in selected_keys
        ):
            marker = "-"
        else:
            continue
        key = (rel, line_number, marker)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{rel}{marker}{line_number}{marker} {text}")
    return lines, len(matches) >= limit


def _parse_rg_records(
    output: bytes, target: Path, run_cwd: Path
) -> list[tuple[str, str, int, str]]:
    records: list[tuple[str, str, int, str]] = []
    for raw_line in output.decode("utf-8").splitlines():
        if not raw_line:
            continue
        payload = json.loads(raw_line)
        kind = payload.get("type")
        if kind not in {"match", "context"}:
            continue
        data = payload["data"]
        path_data = data["path"]
        raw_path = path_data.get("text") or path_data.get("bytes")
        if not isinstance(raw_path, str):
            raise ValueError("rg 路径字段不可解析")
        line_number = int(data["line_number"])
        text = str(data["lines"]["text"]).rstrip("\r\n")
        records.append(
            (
                kind,
                _relative_rg_path(raw_path, target, run_cwd),
                line_number,
                text,
            )
        )
    return records


def _relative_rg_path(raw_path: str, target: Path, run_cwd: Path) -> str:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = run_cwd / candidate
    candidate = candidate.resolve()
    if target.is_file():
        return target.name
    try:
        return candidate.relative_to(target.resolve()).as_posix()
    except ValueError:
        return candidate.name


def _rg_target(target: Path) -> tuple[Path, str]:
    if target.is_file():
        return target.parent, target.name
    return target, "."


def _search_timeout(limits: ToolResourceLimits) -> float:
    return min(limits.timeout or 120.0, limits.max_timeout)
