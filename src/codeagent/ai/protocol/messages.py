"""ModelRuntime 协议与消息模型(框架无关层)。

对应 Pi 的 ``pi-ai`` / ``ModelRuntime``:
- ``ChatClient`` 协议:统一调用面(generate / bind_tools / model_id);
- ``ToolCall`` / ``ChatMessage`` / ``ChatResponse``:OpenAI chat 格式的轻量抽象;
- 流式事件 ``StreamEvent`` 定义在 ``ai/protocol/sse.py``(自研 SSE 解析,
  thinking / usage 全量透传)。

具体传输实现见 ``ai/transport/openai_compat.py``(OpenAI 兼容端点);
编排侧适配经组合根 ``app/container.py`` 的 ``ChatModelPort`` 消费(``ai/bridge``
已随编排自研删除,2026-08-14)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from codeagent.ai.protocol.sse import StreamEvent


@dataclass
class ToolCall:
    """一次工具调用(与 OpenAI function calling 对应)。"""

    id: str
    name: str
    arguments: str  # JSON 字符串(OpenAI 规范)

    def __post_init__(self) -> None:
        # 类型强制:provider 返回已解析对象时序列化为 JSON 字符串;
        # 空串也不合法,回退 "{}"。避免 dict 原样直通请求体导致 provider 400。
        if not isinstance(self.arguments, str):
            self.arguments = json.dumps(self.arguments, ensure_ascii=False)
        elif not self.arguments.strip():
            self.arguments = "{}"


@dataclass
class ChatMessage:
    """一次对话消息(OpenAI chat 格式的轻量抽象)。"""

    role: str            # system / user / assistant / tool
    content: str | list[dict[str, Any]] = ""  # str 或 list(多模态内容块)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""       # tool 角色消息的工具名(转发给供应商校验归属)

    def to_api_dict(self) -> dict[str, Any]:
        """转成 /chat/completions 请求体的消息对象。

        assistant 带 tool_calls 时 content 保留非空旁白、仅无旁白时为 null,
        其余角色 content 为 str 或 list(多模态内容块)。
        """
        d: dict[str, Any] = {"role": self.role}
        if self.tool_calls:
            # OpenAI 规范:assistant+tool_calls 的 content 应为 null(无旁白时),
            # 但非空说明性旁白应保留(否则 ReAct 每轮重建历史时丢失上下文,H7)
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


@dataclass
class ChatResponse:
    """一次生成的结果(流式完成后的汇总)。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    model: str = ""       # 模型标识(映射进 response_metadata,供下游感知)


class ChatClient(Protocol):
    """统一模型客户端协议。

    供应商差异(协议字段/端点)收敛为构造参数 + 实现,调用面统一。
    """

    @property
    def model_id(self) -> str: ...

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[Any] | None = None,
        *,
        stream: bool = False,
    ) -> ChatResponse: ...

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]: ...

    def bind_tools(self, tools: list[Any]) -> "ChatClient": ...
