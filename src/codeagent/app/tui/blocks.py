"""TUI 消息块：用户、助手、活动、工具、错误与取消。

消息块只持有局部显示状态并输出引擎无关的 RichLine。
"""

from __future__ import annotations

import difflib
import re
import time
from collections.abc import Callable
from typing import Any

from codeagent.app.tui.output import OutputBuffer, OutputMetadata
from codeagent.app.tui.primitives import (
    Component, RichLine, _cell_width, _plain, _seg, _truncate, _wrap, _wrap_rich,
)
from codeagent.app.tui.theme import (
    ACCENT, ACTIVITY, ASSISTANT_PROMPT, DIM, DIFF_ADD, DIFF_CONTEXT,
    DIFF_REMOVE, ERROR, SUCCESS, TEXT, TOOL_OUTPUT, USER_BG, USER_PROMPT, WARNING,
)


class UserBlock(Component):
    """用户消息块:低对比提示符与连续的满宽深灰背景。"""

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt

    def render(self, width: int) -> list[RichLine]:
        width = max(1, width)
        body_width = max(1, width - 2)
        lines: list[RichLine] = []
        for index, text in enumerate(_wrap(self.prompt, body_width)):
            prefix = "› " if index == 0 else "  "
            rendered: RichLine = [
                _seg(prefix, fg=USER_PROMPT, bg=USER_BG),
                _seg(text, fg=TEXT, bg=USER_BG),
            ]
            # 按 cell 宽度补齐背景(CJK 双宽;回归:len() 对中文行多算 padding)
            padding = max(0, width - _cell_width(prefix) - _cell_width(text))
            if padding:
                rendered.append(_seg(" " * padding, bg=USER_BG))
            lines.append(rendered)
        return lines


class AssistantBlock(Component):
    """助手回复块:保留推理累积,但只渲染用户可见正文(Markdown 受控渲染)。"""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        md_renderer: Callable[[str, int], list[RichLine]] | None = None,
    ) -> None:
        """``md_renderer`` 为 Markdown 渲染器注入点(design T-46,仿 clock 模式):
        None = 延迟导入默认实现——本模块对 md_renderer 延迟导入以避开
        components ↔ md_renderer 的循环依赖(后者顶层 import 本模块)。"""
        self._clock = clock
        self._md_renderer = md_renderer
        self._thinking_parts: list[str] = []
        self._body_parts: list[str] = []
        self._stable_markdown_cache: dict[tuple[int, str], list[RichLine]] = {}
        self._full_markdown_cache: dict[tuple[int, str], list[RichLine]] = {}
        self._finalized = False
        self.thinking_started: float | None = None
        self.thinking_ended: float | None = None

    def append_thinking(self, text: str) -> None:
        if self.thinking_started is None:
            self.thinking_started = self._clock()
        self._thinking_parts.append(text)
        self.touch()

    def append_text(self, text: str) -> None:
        if self.thinking_started is not None and self.thinking_ended is None:
            self.thinking_ended = self._clock()
        self._body_parts.append(text)
        self._finalized = False
        self.touch()

    def finalize(self) -> None:
        """Mark the block terminal and force the next render to be complete."""
        self._finalized = True
        self._full_markdown_cache.clear()
        self.touch()

    @staticmethod
    def _stable_prefix(body: str) -> str:
        """Return a newline-terminated prefix safe to render independently."""
        end = body.rfind("\n")
        if end < 0:
            return ""
        prefix = body[: end + 1]
        in_fence = False
        for line in prefix.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
        return "" if in_fence else prefix

    @property
    def thinking(self) -> str:
        return "".join(self._thinking_parts)

    @property
    def body(self) -> str:
        return "".join(self._body_parts)

    def render(self, width: int) -> list[RichLine]:
        if not self.body:
            return []
        inner = max(1, width - 2)
        renderer = self._md_renderer
        if renderer is None:
            from codeagent.app.tui.md_renderer import md_renderer as renderer
        body = self.body
        full_key = (inner, body)
        if self._finalized and full_key in self._full_markdown_cache:
            return self._full_markdown_cache[full_key]

        stable = "" if self._finalized else self._stable_prefix(body)
        if stable:
            stable_key = (inner, stable)
            prefix_lines = self._stable_markdown_cache.get(stable_key)
            if prefix_lines is None:
                # ``stable`` ends at the delimiter before the active line;
                # omitting that final delimiter avoids manufacturing an extra
                # empty row when the active tail is rendered separately.
                prefix_lines = renderer(stable[:-1], inner)
                self._stable_markdown_cache[stable_key] = prefix_lines
                if len(self._stable_markdown_cache) > 8:
                    self._stable_markdown_cache.pop(next(iter(self._stable_markdown_cache)))
            tail = body[len(stable) :]
            parsed = [*prefix_lines, *renderer(tail, inner)] if tail else prefix_lines
        else:
            parsed = renderer(body, inner)

        lines: list[RichLine] = []
        for index, line in enumerate(parsed):
            prefix = "• " if index == 0 else "  "
            lines.append([_seg(prefix, fg=ASSISTANT_PROMPT), *line])
        if self._finalized:
            self._full_markdown_cache[full_key] = lines
        return lines


class ActivityBlock(Component):
    """不写入历史的轻量等待提示，由 ``TuiModel`` 控制可见性。"""

    _FRAMES = (" ·", " ··", " ···")

    def __init__(self, frame: int = 0) -> None:
        self.frame = frame

    def render(self, width: int) -> list[RichLine]:
        suffix = self._FRAMES[self.frame % len(self._FRAMES)]
        return [[_seg("• ", fg=ASSISTANT_PROMPT), _seg(f"思考中{suffix}", fg=ACTIVITY)]]


#: 工具参数摘要的最大字符数(超长命令截断)。
_MAX_ARG_SUMMARY = 60


def _tool_path(args: dict[str, Any]) -> str:
    return str(args.get("file_path") or args.get("path") or "")


def _summarize_result(name: str, result: str) -> str | None:
    """工具结果摘要:解析返回文本的关键信息(design D4)。

    bash → ``exit N · Xs``;write → 字节数;edit → 替换处数;解析失败回退首行。
    """
    first = next(
        (line.strip() for line in result.splitlines() if line.strip()), ""
    ) or result.strip()
    if not first:
        return None
    if name == "bash":
        m = re.search(r"退出码:\s*(\d+).*?耗时\s*([\d.]+)s", result)
        if m:
            return f"exit {m.group(1)} · {m.group(2)}s"
    elif name == "write":
        m = re.search(r"已写入 .*?\((\d+)\s*字节\)", result)
        if m:
            return f"{m.group(1)} B"
    elif name == "edit":
        m = re.search(r"已替换\s*(\d+)\s*处", result)
        if m:
            return f"{m.group(1)} 处"
    return _truncate(first, _MAX_ARG_SUMMARY)


class ToolCallBlock(Component):
    """Codex 风格工具摘要与可展开的执行结果/意图差异;含确认环状态(security-permissions)。"""

    def __init__(self, name: str, args: dict[str, Any], call_id: str | None = None) -> None:
        super().__init__()
        self.name = name
        self.args = args
        self.call_id = call_id
        self.status = "pending"  # pending | done | error
        self.execution_status = "running"
        self.result = ""
        self.expanded = False
        #: 等待用户确认(确认请求已发出,尚未响应);拒绝态见 set_rejected。
        self.awaiting = False
        self.rejected = False
        self.output_buffer: OutputBuffer | None = None

    def set_result(
        self,
        result: str,
        error: bool = False,
        execution_status: str | None = None,
        output_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.result = result
        metadata = output_metadata or {}
        self.output_buffer = OutputBuffer(
            result,
            metadata=OutputMetadata(
                total_bytes=int(metadata.get("total_bytes") or len(result.encode("utf-8"))),
                total_lines=int(metadata.get("total_lines") or len(result.splitlines())),
                shown_lines=int(metadata.get("shown_lines") or len(result.splitlines())),
                truncated_by=metadata.get("truncated_by"),
                artifact_path=metadata.get("artifact_path"),
            ),
            page_size=int(metadata.get("page_size") or 40),
        )
        self.status = "error" if error else "done"
        if execution_status:
            self.execution_status = execution_status
        elif not error:
            self.execution_status = "ok"
        self.awaiting = False  # 结果已回填:退出等待确认态
        self.touch()

    def set_awaiting(self) -> None:
        """进入等待确认态(循环已 emit 确认请求;security-permissions)。"""
        self.awaiting = True
        self.touch()

    def set_rejected(self, result: str) -> None:
        """进入拒绝态:结果回填拒绝原因,展示为错误(security-permissions)。"""
        self.result = result
        self.rejected = True
        self.status = "error"
        self.execution_status = "rejected"
        self.awaiting = False
        self.touch()

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
            return pending.get(self.name, f"Running {self.name}")
        if self.status == "error":
            labels = {
                "invalid_arguments": "Invalid arguments",
                "timed_out": "Timed out",
                "cancelled": "Cancelled",
                "cleanup_uncertain": "Cleanup uncertain",
                "rejected": "Rejected",
            }
            return f"{labels.get(self.execution_status, 'Failed')} {self.name}"
        if self.name == "bash":
            result = _summarize_result(self.name, self.result)
            suffix = ""
            if self.output_buffer is not None and (
                self.output_buffer.truncated or self.output_buffer.metadata.total_bytes > 4000
            ):
                suffix = f" · {self.output_buffer.diagnostic}"
            return f"Ran command ({result or 'completed'}{suffix})"
        summary = completed.get(self.name, f"Ran {self.name}")
        if self.output_buffer is not None and self.output_buffer.truncated:
            summary += f" · {self.output_buffer.diagnostic}"
        return summary

    def _edit_summary(self, path: str) -> str:
        old = str(self.args.get("old_string", "")).splitlines()
        new = str(self.args.get("new_string", "")).splitlines()
        return f"Edited {path} (+{len(new)} -{len(old)})"

    def _write_summary(self, path: str) -> str:
        additions = len(str(self.args.get("content", "")).splitlines())
        return f"Wrote {path} (+{additions})"

    def _intent_diff(self, width: int) -> list[RichLine]:
        """渲染请求携带的变更意图，不读取磁盘也不伪称最终文件差异。"""
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
        limit = 80
        matcher = difflib.SequenceMatcher(a=before, b=after)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            entries: list[tuple[str, str, str]] = []
            if tag == "equal":
                entries.extend((" ", value, DIFF_CONTEXT) for value in before[i1:i2])
            else:
                entries.extend(("-", value, DIFF_REMOVE) for value in before[i1:i2])
                entries.extend(("+", value, DIFF_ADD) for value in after[j1:j2])
            for marker, value, bg in entries:
                if emitted >= limit:
                    lines.append([_seg("… 差异内容已截断", fg=DIM)])
                    return lines
                content = _truncate(value, max(1, width - 2))
                lines.append([_seg(f"{marker} {content}", fg=TEXT, bg=bg)])
                emitted += 1
        return lines

    def render(self, width: int) -> list[RichLine]:
        icon, icon_tag = {
            "pending": ("·", DIM),
            "done": ("✓", SUCCESS),
            "error": ("✗", ERROR),
        }[self.status]
        if self.rejected:
            summary = f"Rejected {self.name}"
            summary_tag = ERROR
        elif self.awaiting:
            summary = f"Awaiting confirmation: {self._summary()}"
            summary_tag = WARNING
        else:
            summary = self._summary()
            summary_tag = ERROR if self.status == "error" else ACCENT
        header: RichLine = [
            _seg("▼" if self.expanded else "▶", fg=DIM),
            _seg(" "),
            _seg(icon, fg=icon_tag),
            _seg(" "),
            _seg(summary, fg=summary_tag),
        ]
        lines = [header]
        if self.expanded:
            if self.name in {"edit", "write"} and self.status == "done":
                lines.extend(self._intent_diff(width))
            if self.result:
                if self.output_buffer is not None:
                    if self.output_buffer.truncated or self.output_buffer.metadata.total_bytes > 4000:
                        lines.append([_seg(self.output_buffer.diagnostic, fg=DIM)])
                    lines.extend(
                        _wrap_rich(
                            "\n".join(self.output_buffer.current_page),
                            width,
                            fg=TOOL_OUTPUT,
                        )
                    )
                else:
                    lines.extend(_wrap_rich(self.result, width, fg=TOOL_OUTPUT))
        return lines


class ErrorBlock(Component):
    """错误块(error 红)。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def render(self, width: int) -> list[RichLine]:
        return [_plain("[错误]", fg=ERROR)] + _wrap_rich(self.text, width, fg=ERROR)


class CancelledBlock(Component):
    """运行被取消标记块(warning 黄)。"""

    def render(self, width: int) -> list[RichLine]:
        return [_plain("[已取消]", fg=WARNING)]
