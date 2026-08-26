"""AI 层运行时协议。"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

from codeagent.ai.model.types import (
    ChatMessage,
    ChatResponse,
    StreamEvent,
    ToolDefinition,
)


class Transport(Protocol):
    """模型传输实现提供的最小调用面。"""

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        *,
        stream: bool = False,
    ) -> ChatResponse: ...

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[StreamEvent]: ...

    async def aclose(self) -> None: ...


class ChatClient(Transport, Protocol):
    """供应商差异收敛后的统一模型客户端协议。"""

    @property
    def model_id(self) -> str: ...

    def bind_tools(self, tools: list[ToolDefinition]) -> "ChatClient": ...


class Provider(Protocol):
    """可扩展 provider 对象的预留协议。

    当前内置 provider 仍使用兼容的函数工厂注册表；对象化注册可以在后续
    需要动态发现或懒加载时实现，而不改变调用方契约。
    """

    @property
    def provider_id(self) -> str: ...

    def create_client(
        self,
        *,
        model: str,
        reasoning_effort: str | None = None,
        **kwargs: Any,
    ) -> ChatClient: ...
