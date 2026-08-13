"""app/tui/components.py:纯渲染组件树(样式标签段,引擎无关,可离线测)。

设计(design D1/D3/D4;spec「消息样式区分」):
- 组件输出 ``list[RichLine]``,``RichLine = list[Span]``,``Span = (text, fg, bg)``;
  样式是**受控标签**(theme.py 词表),不是 ANSI——离线断言标签序列;
- 六类消息各带区分样式:用户(背景块)/ Agent(text)/ 思维(thinking 灰,不折叠)/
  工具(状态色图标 + accent 名 + 默认折叠 + 点击展开)/ 错误(error)/ 取消(warning);
- ``TuiModel`` 是「事件 → 组件状态」纯映射(design D3),事件回调只调 ``apply``。

分层约束:本模块可 import ``core``(事件数据形态)+ ``theme``(标签词表),禁止
import textual/终端;禁止 import session/ai/tools。
"""

from __future__ import annotations

import json
import textwrap
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
    USER_BG,
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


class Component:
    """组件基类:纯函数渲染(样式标签段),不碰终端。"""

    def render(self, width: int) -> list[RichLine]:
        raise NotImplementedError(f"{type(self).__name__} 未实现 render")


class UserBlock(Component):
    """用户消息块:背景块(USER_BG),wrap 到宽,text 文字(design D3)。"""

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt

    def render(self, width: int) -> list[RichLine]:
        lines: list[RichLine] = []
        for text in _wrap(self.prompt, width):
            # 文本带 user_bg 背景 + text 前景;补齐到宽保持背景块连续。
            pad = max(0, width - len(text))
            spans = [_seg(text, fg=TEXT, bg=USER_BG)]
            if pad:
                spans.append(_seg(" " * pad, bg=USER_BG))
            lines.append(spans)
        return lines


class AssistantBlock(Component):
    """助手回复块:thinking(灰,始终展开)+ body(text)。"""

    def __init__(self) -> None:
        self._thinking_parts: list[str] = []
        self._body_parts: list[str] = []

    def append_thinking(self, text: str) -> None:
        self._thinking_parts.append(text)

    def append_text(self, text: str) -> None:
        self._body_parts.append(text)

    @property
    def thinking(self) -> str:
        return "".join(self._thinking_parts)

    @property
    def body(self) -> str:
        return "".join(self._body_parts)

    def render(self, width: int) -> list[RichLine]:
        lines: list[RichLine] = []
        if self.thinking:
            # 思维链不折叠:标题(dim)+ 内容(thinking 灰)始终完整渲染(spec「思考过程独立展示」)。
            lines.append(_plain("▸ 思考", fg=DIM))
            lines.extend(_wrap_rich(self.thinking, width, fg=THINKING))
        if self.body:
            lines.extend(_wrap_rich(self.body, width, fg=TEXT))
        elif self._thinking_parts:
            lines.append(_plain("…", fg=DIM))
        return lines


class ToolCallBlock(Component):
    """工具调用块:状态色图标 + accent 名 + dim 参数;结果 tool_output;默认折叠。

    ``expanded`` 默认 False(只渲染 header);点击 header 经 ``toggle_expand`` 切换
    (design D4;spec「工具调用过程可见」「工具调用点击展开」)。
    """

    def __init__(self, name: str, args: str) -> None:
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
            _seg(icon, fg=icon_tag),
            _seg(" "),
            _seg(self.name, fg=ACCENT),
            _seg(f" {self.args}", fg=DIM),
        ]
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


class Editor(Component):
    """输入框的纯渲染表示(MVP:真实编辑由后端 Input 承担;补全/命令缝预留,design D6)。"""

    def __init__(self) -> None:
        self.text = ""

    def render(self, width: int) -> list[RichLine]:
        line = f"▍ {self.text}"
        return [_plain(line[: width if width > 0 else len(line)])]


class TuiModel:
    """「事件 → 组件状态」的纯映射(design D3)。"""

    def __init__(self) -> None:
        self.transcript = Transcript()
        self.status = StatusLine()
        self.running = False
        self._assistant: AssistantBlock | None = None
        self._pending_tools: list[ToolCallBlock] = []

    def _ensure_assistant(self) -> AssistantBlock:
        if self._assistant is None:
            self._assistant = AssistantBlock()
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
                args = (
                    json.dumps(call.get("args", {}), ensure_ascii=False)
                    if isinstance(call, dict)
                    else ""
                )
                block = ToolCallBlock(name, args)
                self.transcript.append(block)
                self._pending_tools.append(block)
        elif ev_type == EventType.TOOL_RESULT:
            # payload 是 ToolMessage.content,不带 tool_call_id;MVP 按 FIFO 归属
            # 最近的 pending 块(并行工具顺序可能不完全精确,已知局限)。
            if self._pending_tools:
                self._pending_tools.pop(0).set_result(str(event.payload or ""))
        elif ev_type == EventType.TURN_END:
            self.running = False
            self.status.status = "IDLE"
            self._assistant = None
        elif ev_type == EventType.ERROR:
            self.transcript.append(ErrorBlock(str(event.payload or "发生错误")))
            self.running = False
            self.status.status = "ERROR"
        elif ev_type == EventType.RUN_CANCELLED:
            self.transcript.append(CancelledBlock())
            self.running = False
            self.status.status = "IDLE"
        elif ev_type == EventType.USAGE:
            usage: dict[str, Any] = event.payload or {}
            self.status.usage = (
                f"↑{usage.get('input_tokens', 0)} "
                f"↓{usage.get('output_tokens', 0)} "
                f"思考{usage.get('reasoning_tokens', 0)}"
            )
