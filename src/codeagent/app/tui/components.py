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
from collections.abc import Callable
from dataclasses import dataclass
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

    def append_text(self, text: str) -> None:
        if self.thinking_started is not None and self.thinking_ended is None:
            self.thinking_ended = self._clock()
        self._body_parts.append(text)

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
        self.name = name
        self.args = args
        self.call_id = call_id
        self.status = "pending"  # pending | done | error
        self.result = ""
        self.expanded = False
        #: 等待用户确认(确认请求已发出,尚未响应);拒绝态见 set_rejected。
        self.awaiting = False
        self.rejected = False

    def set_result(self, result: str, error: bool = False) -> None:
        self.result = result
        self.status = "error" if error else "done"
        self.awaiting = False  # 结果已回填:退出等待确认态

    def set_awaiting(self) -> None:
        """进入等待确认态(循环已 emit 确认请求;security-permissions)。"""
        self.awaiting = True

    def set_rejected(self, result: str) -> None:
        """进入拒绝态:结果回填拒绝原因,展示为错误(security-permissions)。"""
        self.result = result
        self.rejected = True
        self.status = "error"
        self.awaiting = False

    def toggle_expand(self) -> None:
        self.expanded = not self.expanded

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
            return f"Failed {self.name}"
        if self.name == "bash":
            result = _summarize_result(self.name, self.result)
            return f"Ran command ({result or 'completed'})"
        return completed.get(self.name, f"Ran {self.name}")

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

    def append(self, block: Component) -> None:
        self._blocks.append(block)

    def clear(self) -> None:
        """清空聊天区(/clear 命令):重置块与滚动状态。"""
        self._blocks.clear()
        self.follow = True
        self._scroll_top = 0
        self._line_blocks = []

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
            rendered = block.render(width)
            if rendered:
                persistent.append((block, rendered))
        for index, (block, rendered) in enumerate(persistent):
            if index:
                rows.append([])
                owners.append(None)
            rows.extend(rendered)
            owners.extend([block] * len(rendered))
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
        return rich_to_plain(self.all_rich(width))

    def render(
        self, width: int, height: int, transient: Component | None = None
    ) -> list[RichLine]:
        """按视口高度渲染可见行(含跟随/滚动裁剪);同步维护行→块映射。"""
        all_rich, all_blocks = self._rows(width, transient)
        total = len(all_rich)
        height = max(0, height)
        max_start = max(0, total - height)
        if not self.follow and self._scroll_top >= max_start:
            self.follow = True  # 滚到底部恢复跟随
        start = max_start if self.follow else min(self._scroll_top, max_start)
        self._scroll_top = start
        visible = all_rich[start : start + height]
        self._line_blocks = all_blocks[:total][start : start + height]
        return visible

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


class StatusBar(Component):
    """Codex 风格单行状态栏:模型、思考强度与工作目录左对齐显示。"""

    def __init__(self) -> None:
        self.model = ""
        self.effort = ""
        self.cwd = ""

    def render(self, width: int) -> list[RichLine]:
        line: RichLine = [_seg("  ", fg=DIM)]
        if self.model:
            line.append(_seg(self.model, fg=STATUS_MODEL))
        if self.effort:
            line.append(_seg(f" {self.effort}", fg=STATUS_MODEL))
        if self.cwd:
            if self.model or self.effort:
                line.append(_seg(" · ", fg=DIM))
            line.append(_seg(self.cwd, fg=STATUS_PATH))
        return [_truncate_spans(line, max(1, width))]


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

    def render(self, width: int, height: int) -> list[RichLine]:
        transient = ActivityBlock(self.activity_frame) if self.activity_visible else None
        return self.transcript.render(width, height, transient=transient)

    def advance_activity(self) -> None:
        if self.activity_visible:
            self.activity_frame += 1

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

    def apply(self, event: AgentEvent) -> None:
        ev_type = event.type
        if ev_type == EventType.SESSION_STARTED:
            self.transcript.append(UserBlock(str(event.payload)))
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
                    block.set_result(str(event.payload or ""), error=bool(metadata.get("error")))
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
