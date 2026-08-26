"""旧模型契约入口，保留为兼容 re-export。

新代码应从 :mod:`codeagent.ai.model` 导入类型；本模块不再承载实现。
"""

from codeagent.ai.model.protocols import ChatClient
from codeagent.ai.model.types import ChatMessage, ChatResponse, StreamEvent, ToolCall

__all__ = ["ChatClient", "ChatMessage", "ChatResponse", "StreamEvent", "ToolCall"]
