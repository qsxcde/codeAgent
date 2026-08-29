"""把 AI 客户端适配成 core ModelPort。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from codeagent.ai.model.types import ChatMessage, ToolCall as AiToolCall, ToolDefinition
from codeagent.core.context.budget import ContextBudgetInput, ContextBudgetSnapshot, estimate_context_budget
from codeagent.core.contracts.messages import Message, ToolCall
from codeagent.core.contracts.ports import AgentTool, ModelResponse, StreamEvent

from .budget import fit_budget_reserves
from .capabilities import ModelCapabilities


def to_chat_message(message: Message) -> ChatMessage:
    """core Message 转为 AI 层 ChatMessage。"""
    if message.role == "tool":
        return ChatMessage(role="tool", content=message.content, tool_call_id=message.tool_call_id)
    if message.role == "assistant":
        return ChatMessage(
            role="assistant",
            content=message.content,
            tool_calls=[
                AiToolCall(
                    id=call.id,
                    name=call.name,
                    arguments=json.dumps(call.args, ensure_ascii=False),
                )
                for call in message.tool_calls
            ],
        )
    return ChatMessage(role="user", content=message.content)


def usage_of(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """归一供应商 usage 为 core 形状。"""
    if not usage:
        return None
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    details = usage.get("output_token_details") or {}
    reasoning = details.get("reasoning") or usage.get("reasoning_tokens") or 0
    prompt_details = usage.get("prompt_tokens_details") or {}
    cached = prompt_details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "reasoning_tokens": int(reasoning),
        "cached_tokens": int(cached),
    }


def parse_tool_arguments(
    raw: Any,
    *,
    finish_reason: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """在 AI/应用边界解析供应商工具 JSON。"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, None
    if isinstance(raw, dict):
        return dict(raw), None
    if not isinstance(raw, str):
        return {}, "工具参数必须是 JSON 对象"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        suffix = "(可能因响应截断)" if finish_reason == "length" else ""
        return {}, f"工具参数 JSON 无效{suffix}: {exc.msg} (位置 {exc.pos})"
    if not isinstance(value, dict):
        return {}, f"工具参数必须是 JSON 对象,实际为 {type(value).__name__}"
    return value, None


class ChatModelPort:
    """把 ai 层 ChatClient 适配为 core ModelPort。"""

    def __init__(
        self,
        client: Any,
        system_prompt: str | None = None,
        *,
        context_window: int = 128_000,
        output_reserve: int = 4_096,
        reserve_tokens: int = 16_384,
        window_source: str = "fallback",
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._context_window = context_window
        self._output_reserve, self._reserve_tokens = fit_budget_reserves(
            context_window, output_reserve, reserve_tokens
        )
        self._window_source = window_source
        self._capabilities = capabilities or ModelCapabilities(
            model=getattr(client, "model_id", ""),
            context_window=context_window,
            window_source=window_source,
        )

    @property
    def model_id(self) -> str:
        return self._client.model_id

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def output_reserve(self) -> int:
        return self._output_reserve

    @property
    def reserve_tokens(self) -> int:
        return self._reserve_tokens

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return the immutable model capability snapshot."""
        return self._capabilities

    def _prepend_system(self, chat: list[ChatMessage]) -> list[ChatMessage]:
        if self._system_prompt and (not chat or chat[0].role != "system"):
            return [ChatMessage(role="system", content=self._system_prompt), *chat]
        return chat

    def stream(
        self, messages: list[Message], tools: list[AgentTool] | None = None
    ) -> AsyncIterator[StreamEvent]:
        return self._stream(messages, tools)

    def stream_agent(
        self, messages: list[Message], tools: list[AgentTool] | None = None
    ) -> AsyncIterator[StreamEvent]:
        return self._stream_agent(messages, tools)

    @staticmethod
    def _tool_definitions(
        tools: list[AgentTool] | None,
    ) -> list[ToolDefinition] | None:
        if tools is None:
            return None
        definitions: list[ToolDefinition] = []
        for tool in tools:
            if isinstance(tool, AgentTool):
                definitions.append(
                    ToolDefinition(
                        name=tool.name,
                        description=tool.description,
                        parameters=dict(tool.parameters),
                    )
                )
                continue
            raise TypeError(
                "模型工具必须是 AgentTool；"
                "请在组合根先调用 adapt_tools"
            )
        return definitions

    def describe_context_budget(
        self, messages: list[Message], tools: list[AgentTool] | None = None
    ) -> ContextBudgetSnapshot:
        definitions = self._tool_definitions(tools) or []
        return estimate_context_budget(
            ContextBudgetInput(
                context_window=self._context_window,
                output_reserve=self._output_reserve,
                reserve_tokens=self._reserve_tokens,
                system_prompt=self._system_prompt or "",
                tool_definitions=tuple(definition.to_api_dict() for definition in definitions),
                messages=tuple(messages),
                window_source=self._window_source,
            )
        )

    async def _stream(
        self, messages: list[Message], tools: list[AgentTool] | None = None
    ) -> AsyncIterator[StreamEvent]:
        chat = self._prepend_system([to_chat_message(message) for message in messages])
        async for event in self._client.stream(chat, self._tool_definitions(tools)):
            yield StreamEvent(
                type=event.type,
                text=event.text,
                tool_index=event.tool_index,
                arg_delta=event.arg_delta,
                tool_name=event.tool_name,
                tool_id=event.tool_id,
                finish_reason=event.finish_reason,
                usage=usage_of(event.usage),
            )

    async def _stream_agent(
        self, messages: list[Message], tools: list[AgentTool] | None = None
    ) -> AsyncIterator[StreamEvent]:
        chat = self._prepend_system([to_chat_message(message) for message in messages])
        buffers: dict[int, list[str]] = {}
        names: dict[int, str] = {}
        ids: dict[int, str] = {}
        finish_reason: str | None = None
        async for event in self._client.stream(chat, self._tool_definitions(tools)):
            if event.type == "tool_call_arg":
                index = event.tool_index if event.tool_index is not None else 0
                buffers.setdefault(index, []).append(event.arg_delta or "")
                if event.tool_name:
                    names[index] = event.tool_name
                if event.tool_id:
                    ids[index] = event.tool_id
                continue
            if event.type == "finish":
                finish_reason = event.finish_reason
            yield StreamEvent(
                type=event.type,
                text=event.text,
                tool_index=event.tool_index,
                tool_name=event.tool_name,
                tool_id=event.tool_id,
                finish_reason=event.finish_reason,
                usage=usage_of(event.usage),
            )
        for index in sorted(buffers):
            arguments, argument_error = parse_tool_arguments(
                "".join(buffers[index]), finish_reason=finish_reason
            )
            yield StreamEvent(
                type="tool_call",
                tool_index=index,
                tool_name=names.get(index, ""),
                tool_id=ids.get(index, ""),
                arguments=arguments,
                argument_error=argument_error,
            )

    async def generate(
        self, messages: list[Message], tools: list[AgentTool] | None = None
    ) -> ModelResponse:
        chat = self._prepend_system([to_chat_message(message) for message in messages])
        response = await self._client.generate(chat, self._tool_definitions(tools))
        calls: list[ToolCall] = []
        for tool_call in response.tool_calls:
            args, argument_error = parse_tool_arguments(
                tool_call.arguments, finish_reason=response.finish_reason
            )
            calls.append(
                ToolCall(
                    id=tool_call.id,
                    name=tool_call.name,
                    args=args,
                    details={"argument_error": argument_error} if argument_error else {},
                )
            )
        return ModelResponse(
            content=response.content,
            tool_calls=calls,
            usage=usage_of(response.usage),
            finish_reason=response.finish_reason,
            model=response.model,
        )

    async def aclose(self) -> None:
        """释放底层模型客户端。"""
        close = getattr(self._client, "aclose", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
