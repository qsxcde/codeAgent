"""旧模型协议入口，保留为兼容 re-export。"""

from codeagent.ai.protocol.messages import ChatClient, ChatMessage, ChatResponse, ToolCall
from codeagent.ai.protocol.sse import SSEParser, StreamEvent

__all__ = [
    "ChatClient",
    "ChatMessage",
    "ChatResponse",
    "ToolCall",
    "StreamEvent",
    "SSEParser",
]
