"""AI 基础设施包。

AI 层只暴露模型契约、provider、transport 和 catalog。应用级模型选择与
客户端装配位于 ``codeagent.app.composition``；旧的 ``ai.factory`` 仍作为
短期兼容入口存在，但不再由本包顶层导入。
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
