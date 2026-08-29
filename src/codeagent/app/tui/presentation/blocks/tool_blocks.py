"""工具调用摘要和结果块。"""

from __future__ import annotations

import difflib
import re
from typing import Any

from ..output import OutputBuffer, OutputMetadata
from .tool_lifecycle import ToolLifecycleMixin
from ..primitives import (
    Component,
    RichLine,
    _seg,
    _truncate,
    _wrap_rich,
)
from ..theme import (
    ACCENT,
    DIFF_ADD,
    DIFF_CONTEXT,
    DIFF_REMOVE,
    DIM,
    ERROR,
    SUCCESS,
    TEXT,
    TOOL_OUTPUT,
    WARNING,
)

_MAX_ARG_SUMMARY = 60
_SUMMARY_SCAN_CHARS = _MAX_ARG_SUMMARY * 4


def _tool_path(args: dict[str, Any]) -> str:
    return str(args.get("file_path") or args.get("path") or "")


def _summarize_result(name: str, result: str) -> str | None:
    first = _first_nonempty_line(result)
    if not first:
        return None
    if name == "bash":
        match = re.search(r"退出码:\s*(\d+).*?耗时\s*([\d.]+)s", result)
        if match:
            return f"exit {match.group(1)} · {match.group(2)}s"
    elif name == "write":
        match = re.search(r"已写入 .*?\((\d+)\s*字节\)", result)
        if match:
            return f"{match.group(1)} B"
    elif name == "edit":
        match = re.search(r"已替换\s*(\d+)\s*处", result)
        if match:
            return f"{match.group(1)} 处"
    return _truncate(first, _MAX_ARG_SUMMARY)


def _first_nonempty_line(result: str) -> str:
    """Find a bounded summary line without materializing all output lines."""
    start = 0
    while start < len(result):
        newline = result.find("\n", start)
        carriage = result.find("\r", start)
        ends = [position for position in (newline, carriage) if position >= 0]
        end = min(ends) if ends else len(result)
        candidate = result[start : min(end, start + _SUMMARY_SCAN_CHARS)].strip()
        if candidate:
            return candidate
        if end >= len(result):
            break
        start = end + 1
    return ""


class ToolCallBlock(ToolLifecycleMixin, Component):
    """Codex 风格工具摘要与可展开的执行结果/意图差异。"""

    def __init__(self, name: str, args: dict[str, Any], call_id: str | None = None) -> None:
        super().__init__()
        self.name = name
        self.args = args
        self.call_id = call_id
        self.status = "pending"
        self.execution_status = "running"
        self.result = ""
        self.expanded = False
        self.awaiting = False
        self.rejected = False
        self.output_buffer: OutputBuffer | None = None
        self.cleanup_status = "not_required"
        self.elapsed_ms: int | None = None
        self.queue_position: int | None = None
        self.error_code: str | None = None
        self.progress_text = ""
        self._result_applied = False
        self._lifecycle_seen = False

    def toggle_expand(self) -> None:
        self.expanded = not self.expanded
        self.touch()

    def _summary(self) -> str:
        path = _tool_path(self.args)
        pending = {
            "read": f"Reading {path}",
            "edit": f"Editing {path}",
            "write": f"Writing {path}",
            "bash": "Running command",
        }
        completed = {
            "read": f"Read {path}",
            "edit": self._edit_summary(path),
            "write": self._write_summary(path),
        }
        if self.status == "pending":
            if self.execution_status == "queued":
                return pending.get(self.name, f"Queued {self.name}")
            return pending.get(self.name, f"Running {self.name}")
        if self.status == "error":
            labels = {
                "invalid_arguments": "Invalid arguments",
                "timed_out": "Timed out",
                "cancelled": "Cancelled",
                "cleanup_uncertain": "Cleanup uncertain",
                "rejected": "Rejected",
            }
            summary = f"{labels.get(self.execution_status, 'Failed')} {self.name}"
            return summary + self._diagnostic_suffix()
        if self.name == "bash":
            output = self.output_buffer.metadata if self.output_buffer is not None else None
            result = (
                None
                if output is not None and output.source != "legacy" and output.exit_code is not None
                else _summarize_result(self.name, self.result)
            )
            if self.output_buffer is not None:
                if output.exit_code is not None:
                    duration = (
                        f" · {output.duration_ms / 1000:.1f}s"
                        if output.duration_ms is not None
                        else ""
                    )
                    result = f"exit {output.exit_code}{duration}"
            suffix = ""
            if self.output_buffer is not None and (
                self.output_buffer.truncated or self.output_buffer.metadata.total_bytes > 4000
            ):
                suffix = f" · {self.output_buffer.diagnostic}"
            summary = f"Ran command ({result or 'completed'}{suffix})"
            return summary + self._diagnostic_suffix()
        summary = completed.get(self.name, f"Ran {self.name}")
        if self.output_buffer is not None and self.output_buffer.truncated:
            summary += f" · {self.output_buffer.diagnostic}"
        elif self.output_buffer is not None and self.execution_status == "unknown":
            summary += f" · {self.output_buffer.diagnostic}"
        elif self.output_buffer is not None:
            summary += _structured_output_suffix(self.output_buffer.metadata, path)
        return summary + self._diagnostic_suffix()

    def _diagnostic_suffix(self) -> str:
        diagnostics: list[str] = []
        if self.cleanup_status in {"failed", "uncertain", "unsupported"}:
            diagnostics.append("cleanup uncertain")
        if self.elapsed_ms is not None and not (
            self.output_buffer is not None and self.output_buffer.metadata.duration_ms is not None
        ):
            elapsed = f"{self.elapsed_ms / 1000:.1f}s" if self.elapsed_ms >= 1000 else f"{self.elapsed_ms}ms"
            diagnostics.append(elapsed)
        if self.progress_text and self.status == "pending":
            diagnostics.append(self.progress_text)
        return f" · {' · '.join(diagnostics)}" if diagnostics else ""
    def _edit_summary(self, path: str) -> str:
        old = str(self.args.get("old_string", "")).splitlines()
        new = str(self.args.get("new_string", "")).splitlines()
        return f"Edited {path} (+{len(new)} -{len(old)})"

    def _write_summary(self, path: str) -> str:
        additions = len(str(self.args.get("content", "")).splitlines())
        return f"Wrote {path} (+{additions})"

    def _intent_diff(self, width: int) -> list[RichLine]:
        if self.name == "edit":
            before = str(self.args.get("old_string", "")).splitlines()
            after = str(self.args.get("new_string", "")).splitlines()
        elif self.name == "write":
            before = []
            after = str(self.args.get("content", "")).splitlines()
        else:
            return []
        lines: list[RichLine] = [[_seg("intent diff", fg=DIM)]]
        emitted = 0
        matcher = difflib.SequenceMatcher(a=before, b=after)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            entries: list[tuple[str, str, str]] = []
            if tag == "equal":
                entries.extend((" ", value, DIFF_CONTEXT) for value in before[i1:i2])
            else:
                entries.extend(("-", value, DIFF_REMOVE) for value in before[i1:i2])
                entries.extend(("+", value, DIFF_ADD) for value in after[j1:j2])
            for marker, value, bg in entries:
                if emitted >= 80:
                    lines.append([_seg("… 差异内容已截断", fg=DIM)])
                    return lines
                lines.append([_seg(f"{marker} {_truncate(value, max(1, width - 2))}", fg=TEXT, bg=bg)])
                emitted += 1
        return lines
    def render(self, width: int) -> list[RichLine]:
        icon, icon_tag = {"pending": ("·", DIM), "done": ("✓", SUCCESS), "error": ("✗", ERROR)}[
            self.status
        ]
        if self.rejected:
            summary, summary_tag = f"Rejected {self.name}", ERROR
        elif self.awaiting:
            summary, summary_tag = f"Awaiting confirmation: {self._summary()}", WARNING
        else:
            summary = self._summary()
            summary_tag = (
                WARNING
                if self.cleanup_status in {"failed", "uncertain", "unsupported"}
                else ERROR
                if self.status == "error"
                else ACCENT
            )
        lines: list[RichLine] = [[
            _seg("▼" if self.expanded else "▶", fg=DIM),
            _seg(" "),
            _seg(icon, fg=icon_tag),
            _seg(" "),
            _seg(summary, fg=summary_tag),
        ]]
        if self.expanded:
            if self.name in {"edit", "write"} and self.status == "done":
                lines.extend(self._intent_diff(width))
            if self.result:
                if self.output_buffer is not None:
                    if self.output_buffer.truncated or self.output_buffer.metadata.total_bytes > 4000:
                        lines.append([_seg(self.output_buffer.diagnostic, fg=DIM)])
                    lines.extend(_wrap_rich("\n".join(self.output_buffer.current_page), width, fg=TOOL_OUTPUT))
                else:
                    lines.extend(_wrap_rich(self.result, width, fg=TOOL_OUTPUT))
        return lines


def _structured_output_suffix(metadata: OutputMetadata, argument_path: str) -> str:
    """Show structured facts without parsing or copying result text."""
    if metadata.source == "legacy" or metadata.completeness is None:
        return ""
    facts: list[str] = []
    if metadata.path and metadata.path != argument_path:
        facts.append(metadata.path)
    if metadata.range_start is not None or metadata.range_end is not None:
        start = metadata.range_start if metadata.range_start is not None else "?"
        end = metadata.range_end if metadata.range_end is not None else "?"
        facts.append(f"lines {start}-{end}")
    if metadata.total_bytes is not None:
        shown = metadata.shown_bytes if metadata.shown_bytes is not None else "?"
        facts.append(f"{shown}/{metadata.total_bytes} B")
    if metadata.change_summary:
        facts.append(metadata.change_summary)
    if metadata.continuation:
        facts.append("可继续")
    return f" · {' · '.join(facts)}" if facts else ""
