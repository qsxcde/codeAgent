"""模型运行时协议包(框架无关层)。

- ``ToolCall`` / ``ChatMessage`` / ``ChatResponse``:OpenAI chat 格式的轻量抽象;
- ``ChatClient`` 协议:统一调用面(generate / bind_tools / model_id);
- ``StreamEvent`` / ``SSEParser``:流式事件与自研 SSE 解析(thinking / usage 全量透传)。

具体传输实现见 ``codeagent.ai.transport``;组合根在
``codeagent.app.container`` 中把协议适配到自研编排模型端口。
"""

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
