"""AI 层最小模型契约。

本包只包含 provider、transport 与组合根共享的数据类型和协议，
不读取应用配置，也不依赖 core、session 或 tools。
"""

from codeagent.ai.model.protocols import ChatClient, Provider, Transport
from codeagent.ai.model.types import (
    ChatMessage,
    ChatResponse,
    StreamEvent,
    StreamEventType,
    ToolCall,
    ToolDefinition,
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
