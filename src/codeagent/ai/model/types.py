"""provider 无关的模型消息、响应和流事件类型。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

StreamEventType = Literal["content", "thinking", "tool_call_arg", "finish", "usage"]


@dataclass
class ToolCall:
    """一次工具调用(与 OpenAI function calling 对应)。"""

    id: str
    name: str
    arguments: str

    def __post_init__(self) -> None:
        # provider 返回已解析对象时序列化为 JSON 字符串；空串回退为对象，
        # 避免 dict 原样直通请求体导致 provider 400。
        if not isinstance(self.arguments, str):
            self.arguments = json.dumps(self.arguments, ensure_ascii=False)
        elif not self.arguments.strip():
            self.arguments = "{}"


@dataclass
class ChatMessage:
    """一次对话消息(OpenAI chat 格式的轻量抽象)。"""

    role: str
    content: str | list[dict[str, Any]] = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""

    def to_api_dict(self) -> dict[str, Any]:
        """转成 ``/chat/completions`` 请求体的消息对象。"""
        d: dict[str, Any] = {"role": self.role}
        if self.tool_calls:
            # 无旁白时 content 必须保留为 null；非空旁白不能丢失。
            d["content"] = self.content or None
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in self.tool_calls
            ]
        else:
            d["content"] = self.content
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass(frozen=True)
class ToolDefinition:
    """模型可见的中立工具定义。

    组合根把内置工具、MCP 工具或其它工具对象转换为该类型；AI 层不需要
    知道工具的生命周期、权限和实际执行方式。
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def to_api_dict(self) -> dict[str, Any]:
        """转成 OpenAI function calling 的工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ChatResponse:
    """一次生成的结果(流式完成后的汇总)。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    model: str = ""


@dataclass
class StreamEvent:
    """一次 provider 无关的模型流事件。"""

    type: StreamEventType
    text: str = ""
    tool_index: int | None = None
    arg_delta: str = ""
    tool_name: str = ""
    tool_id: str = ""
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
