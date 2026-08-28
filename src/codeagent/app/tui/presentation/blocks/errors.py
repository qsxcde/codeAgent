"""错误和取消消息块。

具体实现按消息、工具职责拆在相邻模块。
"""

from __future__ import annotations

from .message_blocks import ActivityBlock, AssistantBlock, UserBlock
from ..primitives import Component, RichLine, _plain, _wrap_rich
from ..theme import ERROR, WARNING
from .tool_blocks import ToolCallBlock

__all__ = [
    "Component",
    "RichLine",
    "UserBlock",
    "AssistantBlock",
    "ActivityBlock",
    "ToolCallBlock",
    "ErrorBlock",
    "CancelledBlock",
]


class ErrorBlock(Component):
    """错误块。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def render(self, width: int) -> list[RichLine]:
        return [_plain("[错误]", fg=ERROR)] + _wrap_rich(self.text, width, fg=ERROR)


class CancelledBlock(Component):
    """运行被取消标记块。"""

    def render(self, width: int) -> list[RichLine]:
        return [_plain("[已取消]", fg=WARNING)]
