"""模型客户端到 core 端口的组合根适配与模型元数据解析。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from codeagent.ai.model.types import (
    ChatMessage,
    ToolCall as AiToolCall,
    ToolDefinition,
)
from codeagent.core.messages import Message, ToolCall, parse_tool_arguments
from codeagent.core.ports import ModelResponse, StreamEvent

from .model_selection import (
    _provider_config,
    create_llm,
    get_available_providers,
    split_model_pattern,
)


def _to_chat_message(m: Message) -> ChatMessage:
    """core Message → ai 层 ChatMessage(OpenAI 形状)。"""
    if m.role == "tool":
        return ChatMessage(role="tool", content=m.content, tool_call_id=m.tool_call_id)
    if m.role == "assistant":
        return ChatMessage(
            role="assistant",
            content=m.content,
            tool_calls=[
                AiToolCall(
                    id=tc.id,
                    name=tc.name,
                    arguments=json.dumps(tc.args, ensure_ascii=False),
                )
                for tc in m.tool_calls
            ],
        )
    return ChatMessage(role="user", content=m.content)


def _usage_of(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """归一供应商 usage 为 core 形状。"""
    if not usage:
        return None
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    details = usage.get("output_token_details") or {}
    reasoning = details.get("reasoning") or usage.get("reasoning_tokens") or 0
    prompt_details = usage.get("prompt_tokens_details") or {}
    cached = (
        prompt_details.get("cached_tokens")
        or usage.get("prompt_cache_hit_tokens")
        or 0
    )
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "reasoning_tokens": int(reasoning),
        "cached_tokens": int(cached),
    }


class ChatModelPort:
    """把 ai 层 ChatClient 适配为 core ModelPort。"""

    def __init__(self, client: Any, system_prompt: str | None = None) -> None:
        self._client = client
        self._system_prompt = system_prompt

    @property
    def model_id(self) -> str:
        return self._client.model_id

    def _prepend_system(self, chat: list[ChatMessage]) -> list[ChatMessage]:
        """首条非 system 时前置插入 system 消息，仅插入一次。"""
        if self._system_prompt and (not chat or chat[0].role != "system"):
            return [ChatMessage(role="system", content=self._system_prompt), *chat]
        return chat

    def stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self._stream(messages, tools)

    @staticmethod
    def _tool_definitions(tools: list[Any] | None) -> list[ToolDefinition] | None:
        if tools is None:
            return None
        return [
            tool if isinstance(tool, ToolDefinition) else ToolDefinition.from_tool(tool)
            for tool in tools
        ]

    async def _stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        chat = self._prepend_system([_to_chat_message(m) for m in messages])
        async for ev in self._client.stream(chat, self._tool_definitions(tools)):
            yield StreamEvent(
                type=ev.type,
                text=ev.text,
                tool_index=ev.tool_index,
                arg_delta=ev.arg_delta,
                tool_name=ev.tool_name,
                tool_id=ev.tool_id,
                finish_reason=ev.finish_reason,
                usage=_usage_of(ev.usage),
            )

    async def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> ModelResponse:
        chat = self._prepend_system([_to_chat_message(m) for m in messages])
        resp = await self._client.generate(chat, self._tool_definitions(tools))
        calls: list[ToolCall] = []
        for tc in resp.tool_calls:
            args, argument_error = parse_tool_arguments(
                tc.arguments, finish_reason=resp.finish_reason
            )
            calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.name,
                    args=args,
                    argument_error=argument_error,
                )
            )
        return ModelResponse(
            content=resp.content,
            tool_calls=calls,
            usage=_usage_of(resp.usage),
            finish_reason=resp.finish_reason,
            model=resp.model,
        )

    async def aclose(self) -> None:
        """释放底层模型客户端。"""
        close = getattr(self._client, "aclose", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


class LlmSummarizer:
    """使用同一 LLM 通道生成结构化会话摘要。"""

    _SYSTEM_PROMPT = (
        "你是对话摘要器,为继续工作生成结构化上下文检查点摘要。"
        "必须保留精确的文件路径、函数名与错误消息。"
    )
    _PROMPT = (
        "以下是需要压缩的会话消息(完整轮次):\n\n{history}\n\n"
        "既有摘要(必须保留其全部信息,只合并新增内容,不得丢弃):\n{prev}"
    )

    def __init__(self, client: Any) -> None:
        self._client = client

    async def summarize(
        self, messages: list[Any], prev_summary: str | None
    ) -> str:
        history = "\n".join(
            f"{m.role}: {m.content}" for m in messages if getattr(m, "content", "")
        )
        prompt = self._PROMPT.format(
            history=history, prev=prev_summary or "(无)"
        )
        resp = await self._client.generate(
            [
                ChatMessage(role="system", content=self._SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt),
            ],
            tools=None,
        )
        return str(resp.content or "")


def _resolve_model_effort(
    cfg: Any,
    provider: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> tuple[str, str]:
    """解析 model / effort：内联后缀 > 显式 effort > provider 默认。"""
    from codeagent.app.config import Settings

    provider = provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    base, inline = split_model_pattern(model) if model else (None, None)
    effort = inline or reasoning_effort
    model_id = base
    defaults = _provider_config(provider)
    if defaults is not None:
        if model_id is None:
            model_id = defaults.model
        if effort is None:
            effort = defaults.reasoning_effort
    return model_id or "", effort or ""


def _resolve_context_window(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> int:
    """从模型规格解析上下文窗口，缺失时使用 session 兜底值。"""
    from codeagent.app.config import Settings
    from codeagent.session.session import DEFAULT_CONTEXT_WINDOW

    resolved_provider = (
        provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    )
    base = split_model_pattern(model)[0] if model else None
    if registry is not None and base:
        try:
            spec = registry.resolve(base, provider=resolved_provider)
        except (AttributeError, ValueError):
            spec = None
        if spec is not None and getattr(spec, "context_window", None):
            return int(spec.context_window)
    return DEFAULT_CONTEXT_WINDOW
