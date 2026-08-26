"""AI 基础设施包。

AI 层只暴露模型契约、provider、transport 和 catalog。应用级模型选择与
客户端装配位于 ``codeagent.app.composition``，不由本包顶层导入。
"""

from codeagent.ai.model import (
    ChatClient,
    ChatMessage,
    ChatResponse,
    Provider,
    StreamEvent,
    StreamEventType,
    ToolCall,
    ToolDefinition,
    Transport,
)

__all__ = [
    "ChatClient",
    "ChatMessage",
    "ChatResponse",
    "Provider",
    "StreamEvent",
    "StreamEventType",
    "ToolCall",
    "ToolDefinition",
    "Transport",
]
