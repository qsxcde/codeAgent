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

import json
import re
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from codeagent.core.events import AgentEvent, EventType
from codeagent.app.tui.theme import (
    ACCENT,
    DIM,
    ERROR,
    SUCCESS,
    TEXT,
    THINKING,
    TOOL_OUTPUT,
    WARNING,
)

__all__ = [
    "Span",
    "RichLine",
    "Component",
    "UserBlock",
    "AssistantBlock",
    "ToolCallBlock",
    "ErrorBlock",
    "CancelledBlock",
    "Transcript",
    "StatusLine",
    "FooterInfo",
    "FooterLine",
    "Editor",
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


def _wrap(text: str, width: int) -> list[str]:
    """按宽度换行(保留空白、断长词),兼容极窄终端。"""
    width = max(1, width)
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        if len(para) <= width:
            lines.append(para)
            continue
        wrapped = textwrap.wrap(para, width, break_long_words=True, replace_whitespace=False)
        lines.extend(wrapped or [para[:width]])
    return lines


def _wrap_rich(text: str, width: int, fg: str = TEXT, bg: str | None = None) -> list[RichLine]:
    """对纯文本按宽度换行,每行带同一样式标签(换行后的行单样式,design D1)。"""
    return [[_seg(line, fg=fg, bg=bg)] for line in _wrap(text, width)]


def rich_to_plain(lines: list[RichLine]) -> list[str]:
    """把 RichLine 展平为纯文本(退出文档 / 测试用)。"""
    return ["".join(span.text for span in line) for line in lines]


def _truncate(text: str, limit: int) -> str:
    """按字符数截断,超长追加省略号。"""
    return text if len(text) <= limit else text[:limit] + "…"


class Component:
    """组件基类:纯函数渲染(样式标签段),不碰终端。"""

    def render(self, width: int) -> list[RichLine]:
        raise NotImplementedError(f"{type(self).__name__} 未实现 render")


class UserBlock(Component):
    """用户消息块:命令记录行(`❯` accent + 文本 text),无背景(design D2)。

    从全宽背景块改为低对比命令记录:不带 ``USER_BG`` 补齐,靠 `❯` 前缀与
    agent 正文在视觉上区分(参考 Claude Code 用户输入行)。
    """

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt

    def render(self, width: int) -> list[RichLine]:
        return [[_seg("❯ ", fg=ACCENT), _seg(self.prompt, fg=TEXT)]]


class AssistantBlock(Component):
    """助手回复块:thinking(弱化,始终展开)+ body(text)。

    思维链弱化(design D3):元信息标题(耗时/工具数,dim)+ 每行 `│ ` 竖线 +
    THINKING 灰缩进内容;耗时经 ``clock`` 测量:首个 thinking 增量记开始、
    首个正文 token 记结束,两端齐备才显示 ``Thought for Ns``,否则仅「思考」。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._thinking_parts: list[str] = []
        self._body_parts: list[str] = []
        self.thinking_started: float | None = None
        self.thinking_ended: float | None = None
        self.tool_count = 0

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

    def _meta(self) -> str:
        """思考元信息标题(design D3):``Thought for 3s · 1 tool call``。

        思考未结束(尚无正文 token)时只显示「思考」,流式过程中先出现、
        正文到达后补上耗时与工具数。
        """
        if self.thinking_started is None or self.thinking_ended is None:
            return "思考"
        title = f"Thought for {self.thinking_ended - self.thinking_started:.0f}s"
        if self.tool_count:
            unit = "tool call" if self.tool_count == 1 else "tool calls"
            title += f" · {self.tool_count} {unit}"
        return title

    def render(self, width: int) -> list[RichLine]:
        lines: list[RichLine] = []
        if self.thinking:
            # 思维链不折叠:元信息标题(dim)+ `│ ` 竖线缩进内容(thinking 灰)。
            lines.append(_plain(self._meta(), fg=DIM))
            inner = max(1, width - 2)
            for text in _wrap(self.thinking, inner):
                lines.append([_seg("│ ", fg=DIM), _seg(text, fg=THINKING)])
        if self.body:
            lines.extend(_wrap_rich(self.body, width, fg=TEXT))
        elif self._thinking_parts:
            lines.append(_plain("…", fg=DIM))
        return lines


#: 工具参数摘要的最大字符数(超长命令截断)。
_MAX_ARG_SUMMARY = 60


def _summarize_args(name: str, args: dict[str, Any]) -> str:
    """工具专用参数摘要:裸 JSON → 人类可读单行(design D4;不改工具 schema)。

    read/write/edit/ls → 文件路径;bash → 命令;grep → `pattern in path`;
    find → 模式;未知工具回退 JSON。
    """
    if name in ("read", "write", "edit", "ls"):
        text = str(args.get("file_path", ""))
    elif name == "bash":
        text = str(args.get("command", ""))
    elif name == "grep":
        pattern = str(args.get("pattern", ""))
        path = str(args.get("path", ""))
        text = f"{pattern} in {path}" if path else pattern
    elif name == "find":
        text = str(args.get("pattern", ""))
    else:
        text = json.dumps(args, ensure_ascii=False)
    return _truncate(text, _MAX_ARG_SUMMARY)


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
    """工具调用块:折叠符 + 状态图标 + 工具名 + 参数摘要;结果摘要;默认折叠。

    header 重构(design D4):``▶/▼`` 折叠提示(dim)+ 状态图标 + accent 名 +
    工具专用参数摘要(dim);结果返回后折叠态尾附结果摘要;展开显示完整结果。
    构造收结构化 ``args: dict``(工具 schema 原样,摘要由 ``_summarize_args`` 收敛)。
    """

    def __init__(self, name: str, args: dict[str, Any]) -> None:
        self.name = name
        self.args = args
        self.status = "pending"  # pending | done | error
        self.result = ""
        self.expanded = False

    def set_result(self, result: str, error: bool = False) -> None:
        self.result = result
        self.status = "error" if error else "done"

    def toggle_expand(self) -> None:
        self.expanded = not self.expanded

    def render(self, width: int) -> list[RichLine]:
        icon, icon_tag = {
            "pending": ("·", DIM),
            "done": ("✓", SUCCESS),
            "error": ("✗", ERROR),
        }[self.status]
        header: RichLine = [
            _seg("▼" if self.expanded else "▶", fg=DIM),
            _seg(" "),
            _seg(icon, fg=icon_tag),
            _seg(" "),
            _seg(self.name, fg=ACCENT),
            _seg(f" {_summarize_args(self.name, self.args)}", fg=DIM),
        ]
        summary = _summarize_result(self.name, self.result)
        if summary:
            header.append(_seg(f" · {summary}", fg=DIM))
        lines = [header]
        if self.expanded and self.result:
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

    @property
    def blocks(self) -> list[Component]:
        return list(self._blocks)

    def all_rich(self, width: int) -> list[RichLine]:
        """以无界高度渲染全部块(供退出文档 / 视口裁剪)。"""
        lines: list[RichLine] = []
        for block in self._blocks:
            lines.extend(block.render(width))
        return lines

    def all_lines(self, width: int) -> list[str]:
        """以无界高度渲染全部块的纯文本(退出文档,design D6)。"""
        return rich_to_plain(self.all_rich(width))

    def render(self, width: int, height: int) -> list[RichLine]:
        """按视口高度渲染可见行(含跟随/滚动裁剪);同步维护行→块映射。"""
        all_rich = self.all_rich(width)
        total = len(all_rich)
        height = max(0, height)
        max_start = max(0, total - height)
        if not self.follow and self._scroll_top >= max_start:
            self.follow = True  # 滚到底部恢复跟随
        start = max_start if self.follow else min(self._scroll_top, max_start)
        self._scroll_top = start
        visible = all_rich[start : start + height]
        # 行→块映射:把每块渲染的连续行标记为所属块。
        self._line_blocks = []
        for block in self._blocks:
            block_lines = len(block.render(width))
            for _ in range(block_lines):
                if len(self._line_blocks) >= total:
                    break
                self._line_blocks.append(block)
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


class StatusLine(Component):
    """状态栏:状态色(运行 warning / 空闲 success / 错误 error)+ 模型与用量 dim。"""

    def __init__(self) -> None:
        self.status = "IDLE"  # IDLE | RUNNING | ERROR
        self.model = ""
        self.usage = ""

    _STATUS_TAG = {"RUNNING": WARNING, "IDLE": SUCCESS, "ERROR": ERROR}

    def render(self, width: int) -> list[RichLine]:
        segs: RichLine = [_seg(f"[{self.status}] ", fg=self._STATUS_TAG.get(self.status, DIM))]
        if self.model:
            segs.append(_seg(f"{self.model} ", fg=DIM))
        if self.usage:
            segs.append(_seg(self.usage, fg=DIM))
        text = "".join(s.text for s in segs)
        line = text[: width if width > 0 else len(text)]
        return [[_seg(line, fg=self._STATUS_TAG.get(self.status, DIM))]]


@dataclass(frozen=True)
class FooterInfo:
    """底部状态条右端的模型信息(装配时解析固化,design D5)。"""

    model: str = ""
    effort: str = ""


class FooterLine(Component):
    """底部状态条:左端状态/快捷键 + 右端 model · effort(design D5)。

    双端在同一 RichLine 内由空格反推实现右对齐:右端超宽时优先截断右侧。
    """

    def __init__(self) -> None:
        self.status_text = "ready"  # ready | running | error
        self.keys = "Esc 退出"
        self.model = ""
        self.effort = ""

    def render(self, width: int) -> list[RichLine]:
        width = max(1, width)
        left = f"● {self.status_text} · {self.keys}"
        right = " · ".join(x for x in (self.model, self.effort) if x)
        # 右端超宽时优先截断右侧(design D5),保证左端快捷键始终可见。
        right = right[: max(0, width - len(left) - 1)]
        if not right:
            return [_plain(_truncate(left, width), fg=DIM)]
        gap = width - len(left) - len(right)
        return [[_seg(left, fg=DIM), _seg(" " * gap), _seg(right, fg=DIM)]]


class Editor(Component):
    """输入框的纯渲染表示(MVP:真实编辑由后端 Input 承担;补全/命令缝预留,design D6)。"""

    def __init__(self) -> None:
        self.text = ""

    def render(self, width: int) -> list[RichLine]:
        line = f"▍ {self.text}"
        return [_plain(line[: width if width > 0 else len(line)])]


class TuiModel:
    """「事件 → 组件状态」的纯映射(design D3)。

    ``clock`` 可注入(默认 ``time.monotonic``):思考耗时测量依赖它,
    离线测试注入假时钟保持「给定事件序列 → 渲染行」的纯函数性质。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.transcript = Transcript()
        self.status = StatusLine()
        self.footer = FooterLine()
        self.running = False
        self._clock = clock
        self._assistant: AssistantBlock | None = None
        self._pending_tools: list[ToolCallBlock] = []

    def _ensure_assistant(self) -> AssistantBlock:
        if self._assistant is None:
            self._assistant = AssistantBlock(clock=self._clock)
            self.transcript.append(self._assistant)
        return self._assistant

    def apply(self, event: AgentEvent) -> None:
        ev_type = event.type
        if ev_type == EventType.SESSION_STARTED:
            self.transcript.append(UserBlock(str(event.payload)))
            self._assistant = None
            self._pending_tools.clear()
            self.running = True
            self.status.status = "RUNNING"
            self.footer.status_text = "running"
        elif ev_type == EventType.THINKING_DELTA:
            self._ensure_assistant().append_thinking(str(event.payload or ""))
        elif ev_type == EventType.TEXT_DELTA:
            self._ensure_assistant().append_text(str(event.payload or ""))
        elif ev_type == EventType.AGENT_MESSAGE:
            assistant = self._ensure_assistant()
            if not assistant.body:
                assistant.append_text(str(event.payload or ""))
        elif ev_type == EventType.TOOL_CALL:
            for call in event.payload or []:
                name = call.get("name", "?") if isinstance(call, dict) else "?"
                args = call.get("args", {}) if isinstance(call, dict) else {}
                if not isinstance(args, dict):
                    args = {}
                block = ToolCallBlock(name, args)
                self.transcript.append(block)
                self._pending_tools.append(block)
                # 思考元信息里计数工具数(design D3)。
                if self._assistant is not None:
                    self._assistant.tool_count += 1
        elif ev_type == EventType.TOOL_RESULT:
            # payload 是 ToolMessage.content,不带 tool_call_id;MVP 按 FIFO 归属
            # 最近的 pending 块(并行工具顺序可能不完全精确,已知局限)。
            if self._pending_tools:
                self._pending_tools.pop(0).set_result(str(event.payload or ""))
        elif ev_type == EventType.TURN_END:
            self.running = False
            self.status.status = "IDLE"
            self.footer.status_text = "ready"
            self._assistant = None
        elif ev_type == EventType.ERROR:
            self.transcript.append(ErrorBlock(str(event.payload or "发生错误")))
            self.running = False
            self.status.status = "ERROR"
            self.footer.status_text = "error"
        elif ev_type == EventType.RUN_CANCELLED:
            self.transcript.append(CancelledBlock())
            self.running = False
            self.status.status = "IDLE"
            self.footer.status_text = "ready"
        elif ev_type == EventType.USAGE:
            usage: dict[str, Any] = event.payload or {}
            self.status.usage = (
                f"↑{usage.get('input_tokens', 0)} "
                f"↓{usage.get('output_tokens', 0)} "
                f"思考{usage.get('reasoning_tokens', 0)}"
            )
