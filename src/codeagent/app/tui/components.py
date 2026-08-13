"""app/tui/components.py:纯渲染组件树(引擎无关,可离线测)。

职责(design D2/D3/D8):
- 组件是纯对象,``render(width) -> list[str]`` 不碰终端、不 import textual——注入
  脚本化事件序列即可离线断言渲染行(对应 spec「组件渲染离线可测」);
- ``TuiModel`` 是「事件 → 组件状态」的纯映射(design D3):事件回调只调
  ``apply`` 变更状态,渲染调度在别处(view);
- 布局语义:``Transcript`` 可滚动视口独立滚动,``StatusLine`` 固定(design D8)。

分层约束:本模块可 import ``core``(事件数据形态),禁止 import session/ai/tools;
textual 相关一律不在此出现。
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from codeagent.core.events import AgentEvent, EventType

__all__ = [
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

#: 工具调用块的状态图标。
_TOOL_ICONS = {"pending": "·", "done": "✓", "error": "✗"}


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


class Component:
    """组件基类:纯函数渲染,不碰终端。"""

    def render(self, width: int) -> list[str]:
        raise NotImplementedError(f"{type(self).__name__} 未实现 render")


class UserBlock(Component):
    """用户消息块。"""

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt

    def render(self, width: int) -> list[str]:
        return _wrap(f"你: {self.prompt}", width)


class AssistantBlock(Component):
    """助手回复块:thinking 区(可折叠展示) + body 区(流式累积)。"""

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

    def render(self, width: int) -> list[str]:
        lines: list[str] = []
        if self.thinking:
            lines.append("[思考]")
            lines.extend(_wrap(self.thinking, width))
        if self.body:
            lines.extend(_wrap(self.body, width))
        elif self._thinking_parts:
            lines.append("…")  # 仅有思考、正文未出时的进行中占位
        return lines


class ToolCallBlock(Component):
    """工具调用块:name/args + 状态(pending→done/error)+ 截断结果。"""

    def __init__(self, name: str, args: str) -> None:
        self.name = name
        self.args = args
        self.status = "pending"
        self.result = ""

    def set_result(self, result: str, error: bool = False) -> None:
        self.result = result
        self.status = "error" if error else "done"

    def render(self, width: int) -> list[str]:
        icon = _TOOL_ICONS.get(self.status, "·")
        lines = [f"{icon} {self.name}({self.args})"]
        if self.result:
            lines.extend(_wrap(self.result, width))
        return lines


class ErrorBlock(Component):
    """错误块。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def render(self, width: int) -> list[str]:
        return ["[错误]"] + _wrap(self.text, width)


class CancelledBlock(Component):
    """运行被取消标记块。"""

    def render(self, width: int) -> list[str]:
        return ["[已取消]"]


class Transcript(Component):
    """聊天区视口:有序子块 + 滚动状态(follow-end)。

    滚动语义(对应 spec「alt 屏渲染与滚动」):
    - ``follow=True`` 跟底(新内容自动可见);上滚解除跟随;滚到底部恢复跟随。
    """

    def __init__(self) -> None:
        self._blocks: list[Component] = []
        self.follow = True
        self._scroll_top = 0

    def append(self, block: Component) -> None:
        self._blocks.append(block)

    @property
    def blocks(self) -> list[Component]:
        return list(self._blocks)

    def all_lines(self, width: int) -> list[str]:
        """以无界高度渲染全部块(供退出文档用)。"""
        lines: list[str] = []
        for block in self._blocks:
            lines.extend(block.render(width))
        return lines

    def render(self, width: int, height: int) -> list[str]:
        """按视口高度渲染可见行(含跟随/滚动裁剪)。"""
        all_lines = self.all_lines(width)
        total = len(all_lines)
        height = max(0, height)
        max_start = max(0, total - height)
        if not self.follow and self._scroll_top >= max_start:
            self.follow = True  # 滚到底部恢复跟随
        start = max_start if self.follow else min(self._scroll_top, max_start)
        self._scroll_top = start
        return all_lines[start : start + height]

    def scroll(self, delta: int) -> None:
        """按 delta 行滚动;正数上滚(朝向历史,解除跟随),负数下滚(朝向底部)。"""
        if delta > 0:
            self.follow = False
        self._scroll_top = max(0, self._scroll_top - delta)

    def scroll_to_bottom(self) -> None:
        self.follow = True
        self._scroll_top = 0


class StatusLine(Component):
    """状态栏:运行态 + 模型 + 用量(对应 spec「状态栏实时反馈」)。"""

    def __init__(self) -> None:
        self.status = "IDLE"  # IDLE | RUNNING | ERROR
        self.model = ""
        self.usage = ""

    def render(self, width: int) -> list[str]:
        segs = [f"[{self.status}]"]
        if self.model:
            segs.append(self.model)
        if self.usage:
            segs.append(self.usage)
        line = " ".join(segs)
        return [line[: width if width > 0 else len(line)]]


class Editor(Component):
    """输入框的纯渲染表示(MVP:真实编辑由后端 Input 承担)。

    MVP 只呈现占位 + 文本;补全/命令缝(set_completion_provider /
    set_command_handler)预留到下一迭代(design D6),此处不实现。
    """

    def __init__(self) -> None:
        self.text = ""

    def render(self, width: int) -> list[str]:
        line = f"▍ {self.text}"
        return [line[: width if width > 0 else len(line)]]


class TuiModel:
    """「事件 → 组件状态」的纯映射(design D3)。

    事件回调只调 ``apply(event)`` 变更组件状态,不碰渲染;渲染由 view 调度。
    """

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
