"""app/tui/components.py:纯渲染组件树(样式标签段,引擎无关,可离线测)。

设计(design D1/D3/D4;spec「消息样式区分」):
- 组件输出 ``list[RichLine]``,``RichLine = list[Span]``,``Span = (text, fg, bg)``;
  样式是**受控标签**(theme.py 词表),不是 ANSI——离线断言标签序列;
- 六类消息各带区分样式:用户(命令记录行)/ Agent(text)/ 思维(dim 元信息标题 +
  thinking 灰竖线缩进,不折叠)/ 工具(折叠符 + 状态色图标 + accent 名 + 参数摘要,
  默认折叠 + 点击展开)/ 错误(error)/ 取消(warning);
- ``TuiModel`` 是「事件 → 组件状态」纯映射(design D3),事件回调只调 ``apply``;
  思考耗时经可注入 ``clock`` 测量(默认 ``time.monotonic``),离线测试注入假时钟。

分层约束:本模块可 import ``core``(事件数据形态)+ ``theme``(标签词表),禁止
import textual/终端;禁止 import session/ai/tools。
"""

from __future__ import annotations

import difflib
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Any

from codeagent.core.events import AgentEvent, EventType
from codeagent.app.tui.theme import (
    ACCENT,
    ACTIVITY,
    ASSISTANT_PROMPT,
    DIM,
    DIFF_ADD,
    DIFF_CONTEXT,
    DIFF_REMOVE,
    ERROR,
    SUCCESS,
    STATUS_MODEL,
    STATUS_PATH,
    TEXT,
    TOOL_OUTPUT,
    USER_BG,
    USER_PROMPT,
    WARNING,
)
from codeagent.app.tui.runtime import (
    RuntimePhase,
    RuntimeReducer,
    RuntimeSnapshot,
    phase_label,
)
from codeagent.app.tui.output import OutputBuffer, OutputMetadata

__all__ = [
    "Span",
    "RichLine",
    "Component",
    "UserBlock",
    "AssistantBlock",
    "ActivityBlock",
    "ToolCallBlock",
    "ErrorBlock",
    "CancelledBlock",
    "Transcript",
    "StatusBar",
    "FooterInfo",
    "TuiModel",
    "RuntimePhase",
    "RuntimeSnapshot",
    "RuntimeReducer",
]


@dataclass(frozen=True)
class Span:
    """一段带样式的文本:``fg``/``bg`` 是 theme.py 的样式标签,不是 ANSI。"""

    text: str
    fg: str | None = None
    bg: str | None = None


#: 一行 = 段序列(可同行异色:工具块的 状态色图标+accent 名+dim 参数)。
RichLine = list[Span]


def _seg(text: str, fg: str | None = None, bg: str | None = None) -> Span:
    return Span(text, fg=fg, bg=bg)


def _plain(text: str, fg: str = TEXT) -> RichLine:
    return [_seg(text, fg=fg)]


def _cell_width(text: str) -> int:
    """终端 cell 宽度:CJK 等宽/全角字符按 2 格计,其余按 1 格。

    终端按 cell 渲染,而 Python ``len()`` 按字符数——中文等宽字符占 2 cell,
    直接用 len 做换行/截断/背景填充会导致中文行超宽被终端裁掉、背景补齐错位
    (回归)。组合字符/emoji ZWJ 等按 1 格近似,MVP 可接受。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _wrap(text: str, width: int) -> list[str]:
    """按终端 cell 宽度换行(保留空白、断长词),兼容极窄终端。

    与 textwrap 的差异:宽度按 cell 计算(CJK 双宽),断行优先落在字符边界,
    行首尾空白丢弃(近似 textwrap 的 drop_whitespace 语义)。
    """
    width = max(1, width)
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        if _cell_width(para) <= width:
            lines.append(para)
            continue
        lines.extend(_wrap_para(para, width))
    return lines


def _wrap_para(para: str, width: int) -> list[str]:
    """按 cell 宽度逐字符累积换行;断点处的空白不落入行首。"""
    lines: list[str] = []
    current = ""
    current_w = 0
    for ch in para:
        ch_w = _cell_width(ch)
        if current_w + ch_w > width:
            lines.append(current.rstrip())
            # 断点落在空白时,空白不成为新行首(近似 drop_whitespace)
            current = "" if ch == " " else ch
            current_w = 0 if ch == " " else ch_w
        else:
            current += ch
            current_w += ch_w
    if current:
        lines.append(current.rstrip())
    return lines


def _wrap_rich(text: str, width: int, fg: str = TEXT, bg: str | None = None) -> list[RichLine]:
    """对纯文本按宽度换行,每行带同一样式标签(换行后的行单样式,design D1)。"""
    return [[_seg(line, fg=fg, bg=bg)] for line in _wrap(text, width)]


def rich_to_plain(lines: list[RichLine]) -> list[str]:
    """把 RichLine 展平为纯文本(退出文档 / 测试用)。"""
    return ["".join(span.text for span in line) for line in lines]


def _truncate(text: str, limit: int) -> str:
    """按终端 cell 宽度截断(CJK 双宽),超长追加省略号。"""
    if limit <= 0:
        return ""
    if _cell_width(text) <= limit:
        return text
    result = ""
    used = 0
    for ch in text:
        ch_w = _cell_width(ch)
        if used + ch_w > max(0, limit - 1):  # 预留省略号 1 cell
            break
        result += ch
        used += ch_w
    return result + "…"


_MANUAL_SKILL_RE = re.compile(r"^\[用户手动加载技能:\s*([^\]]+)\]")


def _visible_user_content(content: str) -> str:
    """Hide the embedded Skill Markdown from the TUI user transcript.

    Manual Skill loading still stores and sends the original message to the
    model; this formatter only changes what the presentation layer renders.
    """
    match = _MANUAL_SKILL_RE.match(content)
    if match is None:
        return content
    name = match.group(1).strip()
    return f"已加载技能: {name}" if name else "已加载技能"


def _format_token_count(value: int) -> str:
    """把 token 数压缩成状态栏可读的 k/M 单位。"""
    value = max(0, int(value))
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(value)


def _truncate_spans(segs: RichLine, width: int) -> RichLine:
    """按终端 cell 宽度逐段截断(保留各段样式),超宽段加省略号,溢出段丢弃。

    用于状态栏等"多段样式单行":截断不能像纯文本那样整行重上色,
    否则丢失状态色 / dim 的区分(回归)。
    """
    if width <= 0:
        return []
    result: RichLine = []
    remaining = width
    for seg in segs:
        if remaining <= 0:
            break
        text = seg.text
        seg_w = _cell_width(text)
        if seg_w <= remaining:
            result.append(seg)
            remaining -= seg_w
        else:
            keep = ""
            used = 0
            for ch in text:
                ch_w = _cell_width(ch)
                if used + ch_w > max(0, remaining - 1):  # 预留省略号 1 cell
                    break
                keep += ch
                used += ch_w
            result.append(_seg(keep + "…", fg=seg.fg, bg=seg.bg))
            remaining = 0
    return result


class Component:
    """组件基类:纯函数渲染(样式标签段),不碰终端。"""

    def __init__(self) -> None:
        self._revision = 0

    @property
    def revision(self) -> int:
        """内容修订号；渲染缓存只复用相同修订的布局。"""
        return int(getattr(self, "_revision", 0))

    def touch(self) -> None:
        """标记内容发生变化，使 width/revision 缓存失效。"""
        self._revision = self.revision + 1

    def render(self, width: int) -> list[RichLine]:
        raise NotImplementedError(f"{type(self).__name__} 未实现 render")


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
        self.touch()

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
        # 流式:每帧对累积正文全量重解析(design D1 方案 A,body 通常 ≤ 几 KB)。
        lines: list[RichLine] = []
        for index, line in enumerate(renderer(self.body, inner)):
            prefix = "• " if index == 0 else "  "
            lines.append([_seg(prefix, fg=ASSISTANT_PROMPT), *line])
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


class Transcript(Component):
    """聊天区视口:有序子块 + 滚动状态(follow-end)+ 行→块映射(点击命中)。

    滚动语义(对应 spec「alt 屏渲染与滚动」):
    - ``follow=True`` 跟底(新内容自动可见);上滚解除跟随;滚到底部恢复跟随;
    - ``block_at(relative_y)`` 把视口行号映射回所属块(design D4,供工具点击折叠)。
    """

    def __init__(self) -> None:
        self._blocks: list[Component] = []
        self.follow = True
        self._scroll_top = 0
        self._line_blocks: list[Component | None] = []
        self._layout_cache: dict[tuple[int, int, int], list[RichLine]] = {}
        self._last_total = 0
        self._last_block_count = 0
        self._new_output_count = 0
        self.visible_range = (0, 0)
        self.overscan = 2
        self.layout_index: list[tuple[int, int, Component]] = []
        self.overscan_range = (0, 0)
        self.cache_hits = 0
        self.cache_misses = 0

    def append(self, block: Component) -> None:
        self._blocks.append(block)

    def clear(self) -> None:
        """清空聊天区(/clear 命令):重置块与滚动状态。"""
        self._blocks.clear()
        self.follow = True
        self._scroll_top = 0
        self._line_blocks = []
        self._layout_cache.clear()
        self._last_total = 0
        self._last_block_count = 0
        self._new_output_count = 0
        self.visible_range = (0, 0)
        self.layout_index = []
        self.overscan_range = (0, 0)

    @property
    def new_output_count(self) -> int:
        """用户离开底部后累积的新输出块数量。"""
        return self._new_output_count

    @property
    def blocks(self) -> list[Component]:
        return list(self._blocks)

    def _rows(
        self, width: int, transient: Component | None = None
    ) -> tuple[list[RichLine], list[Component | None]]:
        """构造内容行与点击映射；块间空行、瞬态行均不命中点击。"""
        rows: list[RichLine] = []
        owners: list[Component | None] = []
        persistent: list[tuple[Component, list[RichLine]]] = []
        for block in self._blocks:
            key = (id(block), width, int(getattr(block, "revision", 0)))
            rendered = self._layout_cache.get(key)
            if rendered is None:
                rendered = block.render(width)
                self._layout_cache[key] = rendered
                self.cache_misses += 1
            else:
                self.cache_hits += 1
            if rendered:
                persistent.append((block, rendered))
        self.layout_index = []
        cursor = 0
        for index, (block, rendered) in enumerate(persistent):
            if index:
                rows.append([])
                owners.append(None)
                cursor += 1
            start = cursor
            rows.extend(rendered)
            owners.extend([block] * len(rendered))
            cursor += len(rendered)
            self.layout_index.append((start, cursor, block))
        if transient is not None:
            rendered = transient.render(width)
            if rendered:
                if rows:
                    rows.append([])
                    owners.append(None)
                rows.extend(rendered)
                owners.extend([None] * len(rendered))
        return rows, owners

    def all_rich(self, width: int) -> list[RichLine]:
        """以无界高度渲染全部块(供退出文档 / 视口裁剪)。"""
        return self._rows(width)[0]

    def all_lines(self, width: int) -> list[str]:
        """以无界高度渲染全部块的纯文本(退出文档,design D6)。"""
        return list(self.iter_lines(width))

    def iter_lines(self, width: int) -> Iterator[str]:
        """按顶层块逐行生成完整退出文档，避免先构造超大 list。"""
        first = True
        for block in self._blocks:
            key = (id(block), width, int(getattr(block, "revision", 0)))
            rendered = self._layout_cache.get(key)
            if rendered is None:
                rendered = block.render(width)
                self._layout_cache[key] = rendered
                self.cache_misses += 1
            else:
                self.cache_hits += 1
            if not rendered:
                continue
            if not first:
                yield ""
            first = False
            for line in rendered:
                yield "".join(span.text for span in line)

    def render(
        self, width: int, height: int, transient: Component | None = None
    ) -> list[RichLine]:
        """只物化视口及 overscan 范围内的块，维护行→块映射。"""
        height = max(0, height)
        if not self.follow and len(self._blocks) > self._last_block_count:
            self._new_output_count += len(self._blocks) - self._last_block_count

        transient_rendered: list[RichLine] = []
        entries: list[tuple[Component, int, int, list[RichLine] | None]] = []
        total = 0
        start = 0
        for _ in range(2):
            entries, total, transient_entry = self._layout_entries(width, transient)
            max_start = max(0, total - height)
            if not self.follow and self._scroll_top >= max_start:
                self.follow = True  # 滚到底部恢复跟随
            start = max_start if self.follow else min(self._scroll_top, max_start)
            self._scroll_top = start
            window_start = max(0, start - self.overscan)
            window_end = min(total, start + height + self.overscan)
            changed = False
            for block, block_start, block_end, rendered in entries:
                if rendered is None and block_end > window_start and block_start < window_end:
                    self._cache_block(block, width)
                    changed = True
            if transient_entry is not None:
                _, transient_start, transient_end, _ = transient_entry
                if transient_end > window_start and transient_start < window_end:
                    transient_rendered = transient.render(width) if transient is not None else []
            if not changed:
                break

        # Materialization can change a block's height; use the final layout for
        # the visible slice and its click owners.
        entries, total, transient_entry = self._layout_entries(width, transient)
        max_start = max(0, total - height)
        if self.follow:
            start = max_start
        else:
            start = min(self._scroll_top, max_start)
        self._scroll_top = start
        visible_end = start + height
        visible_pairs: list[tuple[int, RichLine, Component | None]] = []
        for entry_index, (block, block_start, _, rendered) in enumerate(entries):
            if rendered is None:
                continue
            if entry_index:
                separator = block_start - 1
                if start <= separator < visible_end:
                    visible_pairs.append((separator, [], None))
            for index, line in enumerate(rendered, start=block_start):
                if start <= index < visible_end:
                    visible_pairs.append((index, line, block))
        if transient_entry is not None:
            _, transient_start, _, _ = transient_entry
            if entries:
                separator = transient_start - 1
                if start <= separator < visible_end:
                    visible_pairs.append((separator, [], None))
            for index, line in enumerate(transient_rendered, start=transient_start):
                if start <= index < visible_end:
                    visible_pairs.append((index, line, None))
        visible_pairs.sort(key=lambda item: item[0])
        visible = [line for _, line, _ in visible_pairs]
        owners = [owner for _, _, owner in visible_pairs]
        self._line_blocks = owners
        self.visible_range = (start, min(total, start + len(visible)))
        self.overscan_range = (
            max(0, start - self.overscan),
            min(total, start + height + self.overscan),
        )
        self._last_total = total
        self._last_block_count = len(self._blocks)
        if self.follow:
            self._new_output_count = 0
        return visible

    def _cache_block(self, block: Component, width: int) -> list[RichLine]:
        key = (id(block), width, int(getattr(block, "revision", 0)))
        rendered = self._layout_cache.get(key)
        if rendered is None and key not in self._layout_cache:
            rendered = block.render(width)
            self._layout_cache[key] = rendered
            self.cache_misses += 1
        elif rendered is not None:
            self.cache_hits += 1
        return rendered or []

    def _layout_entries(
        self, width: int, transient: Component | None
    ) -> tuple[
        list[tuple[Component, int, int, list[RichLine] | None]],
        int,
        tuple[Component, int, int, list[RichLine] | None] | None,
    ]:
        entries: list[tuple[Component, int, int, list[RichLine] | None]] = []
        cursor = 0
        self.layout_index = []
        for block in self._blocks:
            key = (id(block), width, int(getattr(block, "revision", 0)))
            rendered = self._layout_cache.get(key)
            if rendered is None and key not in self._layout_cache:
                # A single row is a conservative estimate until a visible
                # block is materialized; empty assistant blocks are free.
                height = 0 if isinstance(block, AssistantBlock) and not block.body else 1
                if height == 0:
                    continue
            else:
                if not rendered:
                    continue
                height = len(rendered)
            if entries:
                cursor += 1
            block_start = cursor
            block_end = block_start + height
            entries.append((block, block_start, block_end, rendered))
            self.layout_index.append((block_start, block_end, block))
            cursor = block_end
        transient_entry = None
        if transient is not None:
            if entries:
                cursor += 1
            transient_entry = (transient, cursor, cursor + 1, None)
            cursor += 1
        # ``layout_index`` is an index of the current estimates, not a cache
        # of rendered rows; callers can use it before every block is painted.
        return entries, cursor, transient_entry

    def block_at(self, relative_y: int) -> Component | None:
        """返回视口第 relative_y 行所属的块(越界 / 空返回 None)。"""
        if 0 <= relative_y < len(self._line_blocks):
            return self._line_blocks[relative_y]
        return None

    def scroll(self, delta: int) -> None:
        """按 delta 行滚动;正数上滚(朝向历史,解除跟随),负数下滚(朝向底部)。"""
        if delta > 0:
            self.follow = False
        self._scroll_top = max(0, self._scroll_top - delta)

    def scroll_to_bottom(self) -> None:
        self.follow = True
        self._scroll_top = 0
        self._new_output_count = 0


class StatusBar(Component):
    """Codex 风格单行状态栏:左侧元数据 + 右侧上下文占用。"""

    _CONTEXT_BAR_WIDTH = 8

    def __init__(self) -> None:
        self.model = ""
        self.effort = ""
        self.cwd = ""
        #: 最近一次请求的输入 token;None = 尚未收到 provider usage。
        self.context_tokens: int | None = None
        #: 上下文窗口上限;None = 装配层尚未提供上下文元数据。
        self.context_window: int | None = None
        self.runtime = RuntimeSnapshot()
        self.runtime_visible = False
        self.new_output_count = 0

    def apply_snapshot(self, snapshot: RuntimeSnapshot, now: float | None = None) -> None:
        """同步运行快照，并把阶段耗时更新为当前显示时刻。"""
        elapsed_ms = snapshot.elapsed(now)
        self.runtime_visible = True
        self.runtime = replace(snapshot, elapsed_ms=elapsed_ms)
        self.context_tokens = snapshot.context_tokens
        self.context_window = snapshot.context_window

    def refresh_runtime(self, now: float | None = None) -> None:
        """只刷新阶段计时，不改变其它状态。"""
        self.apply_snapshot(self.runtime, now)

    def render(self, width: int) -> list[RichLine]:
        left: RichLine = [_seg("  ", fg=DIM)]
        runtime = self.runtime
        if self.runtime_visible:
            left.append(_seg(phase_label(runtime.phase), fg=WARNING if runtime.phase in {
                RuntimePhase.ERROR,
                RuntimePhase.CANCELLING,
                RuntimePhase.AWAITING_CONFIRMATION,
            } else ACCENT))
            if runtime.phase_started_at is not None:
                left.append(_seg(f" {runtime.elapsed_ms / 1000:.1f}s", fg=DIM))
            if runtime.current_operation:
                left.append(_seg(f" · {runtime.current_operation}", fg=DIM))
            if runtime.context_stale:
                left.append(_seg(" · 上下文同步中", fg=WARNING))
            if self.new_output_count:
                left.append(_seg(f" · 新输出 {self.new_output_count}", fg=WARNING))
        if self.model:
            left.append(_seg(self.model, fg=STATUS_MODEL))
        if self.effort:
            left.append(_seg(f" {self.effort}", fg=STATUS_MODEL))
        if self.cwd:
            if self.model or self.effort:
                left.append(_seg(" · ", fg=DIM))
            left.append(_seg(self.cwd, fg=STATUS_PATH))

        right = self._context_line()
        width = max(1, width)
        if not right:
            return [_truncate_spans(left, width)]

        right_width = sum(_cell_width(span.text) for span in right)
        if right_width >= width:
            return [_truncate_spans(right, width)]

        left = _truncate_spans(left, max(1, width - right_width - 1))
        gap = max(1, width - _cell_width("".join(span.text for span in left)) - right_width)
        return [left + [_seg(" " * gap, fg=DIM)] + right]

    def _context_line(self) -> RichLine:
        """渲染右对齐的上下文进度条与占用标签。"""
        if self.context_window is None or self.context_window <= 0:
            return []
        window = self.context_window
        used = self.context_tokens
        if used is None:
            filled = 0
            label = f"上下文 — / {_format_token_count(window)}"
        else:
            ratio = max(0.0, min(1.0, used / window))
            filled = round(ratio * self._CONTEXT_BAR_WIDTH)
            percent = ratio * 100
            label = (
                f"上下文 {_format_token_count(max(0, used))} / "
                f"{_format_token_count(window)} · {percent:.1f}%"
            )
        meter = "▰" * filled + "▱" * (self._CONTEXT_BAR_WIDTH - filled)
        return [_seg(f"{meter} ", fg=ACCENT), _seg(label, fg=ACCENT)]


@dataclass(frozen=True)
class FooterInfo:
    """底部状态栏装配数据(装配时解析固化,design D5)。

    - ``model`` / ``effort``:状态栏中的模型与思考强度;
    - ``provider``:当前 provider(选择面板 ✓ 标记用;状态栏不显示);
    - ``cwd``:状态栏显示的工作目录。
    """

    model: str = ""
    effort: str = ""
    provider: str = ""
    cwd: str = ""


class TuiModel:
    """「事件 → 组件状态」的纯映射(design D3)。

    ``clock`` 可注入(默认 ``time.monotonic``):思考耗时测量依赖它,
    离线测试注入假时钟保持「给定事件序列 → 渲染行」的纯函数性质。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.transcript = Transcript()
        self.status = StatusBar()
        self.running = False
        self._clock = clock
        self._assistant: AssistantBlock | None = None
        self._pending_tools: list[ToolCallBlock] = []
        self._pending_tools_by_id: dict[str, ToolCallBlock] = {}
        self.activity_visible = False
        self.activity_frame = 0
        self.runtime = RuntimeSnapshot()
        self._runtime_reducer = RuntimeReducer(clock=clock)
        self.render_stats: dict[str, int | float] = {
            "frames": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "last_render_ms": 0.0,
        }
        self.output_stats: dict[str, int] = {
            "results": 0,
            "truncated": 0,
            "bytes": 0,
            "lines": 0,
        }

    def render(self, width: int, height: int) -> list[RichLine]:
        started = self._clock()
        transient = ActivityBlock(self.activity_frame) if self.activity_visible else None
        lines = self.transcript.render(width, height, transient=transient)
        self.status.new_output_count = self.transcript.new_output_count
        self.render_stats["cache_hits"] = self.transcript.cache_hits
        self.render_stats["cache_misses"] = self.transcript.cache_misses
        self.render_stats["frames"] = int(self.render_stats["frames"]) + 1
        self.render_stats["last_render_ms"] = round((self._clock() - started) * 1000, 3)
        return lines

    def advance_activity(self) -> None:
        if self.activity_visible:
            self.activity_frame += 1

    def set_context_status(
        self,
        tokens: int | None,
        window: int | None,
        *,
        stale: bool = False,
    ) -> None:
        """同步组合根/会话层提供的上下文窗口信息。"""
        self.runtime = replace(
            self.runtime,
            context_tokens=tokens,
            context_window=window,
            context_stale=stale,
        )
        self.status.apply_snapshot(self.runtime, now=self._clock())

    def _ensure_assistant(self) -> AssistantBlock:
        if self._assistant is None:
            self._assistant = AssistantBlock(clock=self._clock)
            self.transcript.append(self._assistant)
        return self._assistant

    def append_info(self, text: str) -> None:
        """追加一条命令输出块(纯 TUI 显示,不进入会话历史,不改运行态)。"""
        block = AssistantBlock(clock=self._clock)
        block.append_text(text)
        self.transcript.append(block)

    def page_output(self, delta: int, call_id: str | None = None) -> bool:
        """切换工具输出页，只改变视图游标。"""
        candidates = [
            block
            for block in self.transcript.blocks
            if isinstance(block, ToolCallBlock) and block.output_buffer is not None
        ]
        if call_id:
            candidates = [block for block in candidates if block.call_id == call_id]
        if not candidates:
            return False
        block = candidates[-1]
        changed = block.output_buffer.next_page() if delta > 0 else block.output_buffer.previous_page()
        if changed:
            block.touch()
        return changed

    def export_output(self, path: str, call_id: str | None = None) -> str:
        """显式导出工具原始输出，返回可定位路径。"""
        candidates = [
            block
            for block in self.transcript.blocks
            if isinstance(block, ToolCallBlock) and block.output_buffer is not None
        ]
        if call_id:
            candidates = [block for block in candidates if block.call_id == call_id]
        if not candidates:
            raise ValueError("没有可导出的工具输出")
        return str(candidates[-1].output_buffer.export(path))

    def hydrate_history(self, history: list[Any], summary: str | None = None) -> None:
        """从会话快照重建 transcript,用于切换/恢复持久化会话。

        ``AgentSession`` 的历史是消息模型,而 TUI 运行时状态来自事件流。
        切换会话不会重新发出过去的事件,因此这里按消息顺序重建同一组可见块,
        并将尚未有结果的工具调用保留为 pending。该方法只负责显示历史,
        不会把任何消息重新写回会话或触发模型调用。
        """
        self.transcript.clear()
        self.running = False
        self._assistant = None
        self._pending_tools.clear()
        self._pending_tools_by_id.clear()
        self.activity_visible = False
        self.activity_frame = 0

        if summary:
            self.append_info(f"上下文摘要\n{summary}")

        for message in history:
            role = str(getattr(message, "role", ""))
            content = str(getattr(message, "content", "") or "")
            if role == "user":
                self.transcript.append(UserBlock(_visible_user_content(content)))
                self._assistant = None
                continue

            if role == "assistant":
                if content:
                    block = AssistantBlock(clock=self._clock)
                    block.append_text(content)
                    self.transcript.append(block)
                self._assistant = None
                for call in getattr(message, "tool_calls", None) or []:
                    if isinstance(call, dict):
                        name = str(call.get("name") or "?")
                        args = call.get("args") or {}
                        call_id = call.get("id")
                    else:
                        name = str(getattr(call, "name", "?") or "?")
                        args = getattr(call, "args", {}) or {}
                        call_id = getattr(call, "id", None)
                    if not isinstance(args, dict):
                        args = {}
                    block = ToolCallBlock(
                        name,
                        args,
                        call_id=str(call_id) if call_id else None,
                    )
                    self.transcript.append(block)
                    self._pending_tools.append(block)
                    if block.call_id:
                        self._pending_tools_by_id[block.call_id] = block
                continue

            if role == "tool":
                call_id = str(getattr(message, "tool_call_id", "") or "")
                block = self._pending_tools_by_id.pop(call_id, None) if call_id else None
                if block is None and self._pending_tools:
                    block = self._pending_tools[0]
                    if block.call_id:
                        self._pending_tools_by_id.pop(block.call_id, None)
                if block is not None:
                    self._pending_tools.remove(block)
                    block.set_result(content, execution_status="ok")

        self.transcript.scroll_to_bottom()

    def apply(self, event: AgentEvent) -> None:
        self.runtime = self._runtime_reducer.apply(self.runtime, event)
        self.status.apply_snapshot(self.runtime, now=self._clock())
        self.running = self.runtime.phase in {
            RuntimePhase.WAITING_MODEL,
            RuntimePhase.STREAMING,
            RuntimePhase.TOOL_RUNNING,
            RuntimePhase.AWAITING_CONFIRMATION,
            RuntimePhase.COMPACTING,
            RuntimePhase.CANCELLING,
            RuntimePhase.RESTORING,
        }
        ev_type = event.type
        if ev_type == EventType.SESSION_STARTED:
            self.transcript.append(UserBlock(_visible_user_content(str(event.payload))))
            self._assistant = None
            self._pending_tools.clear()
            self._pending_tools_by_id.clear()
            self.running = True
            self.activity_visible = True
            self.activity_frame = 0
        elif ev_type == EventType.THINKING_DELTA:
            self._ensure_assistant().append_thinking(str(event.payload or ""))
            self.activity_visible = True
        elif ev_type == EventType.TEXT_DELTA:
            self._ensure_assistant().append_text(str(event.payload or ""))
            self.activity_visible = False
        elif ev_type == EventType.AGENT_MESSAGE:
            assistant = self._ensure_assistant()
            if not assistant.body:
                assistant.append_text(str(event.payload or ""))
            self.activity_visible = False
        elif ev_type == EventType.TOOL_CALL:
            for call in event.payload or []:
                name = call.get("name", "?") if isinstance(call, dict) else "?"
                args = call.get("args", {}) if isinstance(call, dict) else {}
                if not isinstance(args, dict):
                    args = {}
                call_id = str(call.get("id")) if isinstance(call, dict) and call.get("id") else None
                block = ToolCallBlock(name, args, call_id=call_id)
                self.transcript.append(block)
                self._pending_tools.append(block)
                if call_id:
                    self._pending_tools_by_id[call_id] = block
            self.activity_visible = False
            self._assistant = None
        elif ev_type == EventType.TOOL_RESULT:
            metadata = event.metadata or {}
            self.output_stats["results"] += 1
            self.output_stats["bytes"] += int(metadata.get("total_bytes") or len(str(event.payload or "").encode("utf-8")))
            self.output_stats["lines"] += int(metadata.get("total_lines") or len(str(event.payload or "").splitlines()))
            if metadata.get("truncated_by"):
                self.output_stats["truncated"] += 1
            call_id = metadata.get("tool_call_id")
            block = self._pending_tools_by_id.pop(str(call_id), None) if call_id else None
            if block is not None:
                if block in self._pending_tools:
                    self._pending_tools.remove(block)
            elif self._pending_tools:
                block = self._pending_tools.pop(0)
                if block.call_id:
                    self._pending_tools_by_id.pop(block.call_id, None)
            if block is not None:
                if metadata.get("rejected"):
                    block.set_rejected(str(event.payload or ""))
                else:
                    block.set_result(
                        str(event.payload or ""),
                        error=bool(metadata.get("error")),
                        execution_status=str(metadata.get("status") or ""),
                        output_metadata=metadata,
                    )
            if not self._pending_tools:
                self.activity_visible = True
        elif ev_type == EventType.CONFIRMATION_REQUESTED:
            # 确认请求:标记对应工具块为等待确认(security-permissions)。
            payload = event.payload or {}
            call_id = str(payload.get("tool_call_id") or "")
            block = self._pending_tools_by_id.get(call_id)
            if block is None and self._pending_tools:
                block = self._pending_tools[0]
            if block is not None:
                block.set_awaiting()
            self.activity_visible = False
        elif ev_type == EventType.TURN_END:
            self.running = False
            self._assistant = None
            self.activity_visible = False
        elif ev_type == EventType.ERROR:
            self.transcript.append(ErrorBlock(str(event.payload or "发生错误")))
            self.running = False
            self.activity_visible = False
        elif ev_type == EventType.RUN_CANCELLED:
            self.transcript.append(CancelledBlock())
            self.running = False
            self.activity_visible = False
