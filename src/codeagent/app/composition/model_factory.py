"""模型客户端到 core 端口的组合根适配与模型元数据解析。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

from codeagent.ai.model.types import (
    ChatMessage,
    ToolCall as AiToolCall,
    ToolDefinition,
)
from codeagent.core.messages import Message, ToolCall
from codeagent.core.context_budget import (
    ContextBudgetInput,
    ContextBudgetSnapshot,
    estimate_context_budget,
)
from codeagent.core.ports import ModelResponse, StreamEvent

from .model_selection import (
    _get_default_registry,
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


def _parse_tool_arguments(
    raw: Any,
    *,
    finish_reason: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Parse provider tool JSON at the AI/application boundary."""
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


def _fit_budget_reserves(
    context_window: int,
    output_reserve: int,
    reserve_tokens: int,
) -> tuple[int, int]:
    """Fit optional reservations inside a valid positive context window."""
    if type(context_window) is not int or context_window < 1:
        return output_reserve, reserve_tokens
    if type(output_reserve) is int and output_reserve >= 0:
        output_reserve = min(output_reserve, context_window)
    if type(reserve_tokens) is int and reserve_tokens >= 0:
        remaining = max(0, context_window - output_reserve)
        reserve_tokens = min(reserve_tokens, remaining)
    return output_reserve, reserve_tokens


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
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._context_window = context_window
        self._output_reserve, self._reserve_tokens = _fit_budget_reserves(
            context_window, output_reserve, reserve_tokens
        )
        self._window_source = window_source

    @property
    def model_id(self) -> str:
        return self._client.model_id

    @property
    def context_window(self) -> int:
        """Effective model context window exposed to session composition."""
        return self._context_window

    @property
    def output_reserve(self) -> int:
        """Effective output reservation used by request budget estimation."""
        return self._output_reserve

    @property
    def reserve_tokens(self) -> int:
        """Effective safety reservation used by request budget estimation."""
        return self._reserve_tokens

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

    def stream_agent(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream core events with provider tool arguments already decoded."""
        return self._stream_agent(messages, tools)

    @staticmethod
    def _tool_definitions(tools: list[Any] | None) -> list[ToolDefinition] | None:
        if tools is None:
            return None
        return [
            tool if isinstance(tool, ToolDefinition) else ToolDefinition.from_tool(tool)
            for tool in tools
        ]

    def describe_context_budget(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> ContextBudgetSnapshot:
        """Describe the request after applying this adapter's request rules."""
        definitions = self._tool_definitions(tools) or []
        return estimate_context_budget(
            ContextBudgetInput(
                context_window=self._context_window,
                output_reserve=self._output_reserve,
                reserve_tokens=self._reserve_tokens,
                system_prompt=self._system_prompt or "",
                tool_definitions=tuple(
                    definition.to_api_dict() for definition in definitions
                ),
                messages=tuple(messages),
                window_source=self._window_source,
            )
        )

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

    async def _stream_agent(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        chat = self._prepend_system([_to_chat_message(m) for m in messages])
        buffers: dict[int, list[str]] = {}
        names: dict[int, str] = {}
        ids: dict[int, str] = {}
        finish_reason: str | None = None
        async for ev in self._client.stream(chat, self._tool_definitions(tools)):
            if ev.type == "tool_call_arg":
                index = ev.tool_index if ev.tool_index is not None else 0
                buffers.setdefault(index, []).append(ev.arg_delta or "")
                if ev.tool_name:
                    names[index] = ev.tool_name
                if ev.tool_id:
                    ids[index] = ev.tool_id
                continue
            if ev.type == "finish":
                finish_reason = ev.finish_reason
            yield StreamEvent(
                type=ev.type,
                text=ev.text,
                tool_index=ev.tool_index,
                tool_name=ev.tool_name,
                tool_id=ev.tool_id,
                finish_reason=ev.finish_reason,
                usage=_usage_of(ev.usage),
            )
        for index in sorted(buffers):
            arguments, argument_error = _parse_tool_arguments(
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
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> ModelResponse:
        chat = self._prepend_system([_to_chat_message(m) for m in messages])
        resp = await self._client.generate(chat, self._tool_definitions(tools))
        calls: list[ToolCall] = []
        for tc in resp.tool_calls:
            args, argument_error = _parse_tool_arguments(
                tc.arguments, finish_reason=resp.finish_reason
            )
            calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.name,
                    args=args,
                    details={"argument_error": argument_error} if argument_error else {},
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

    async def aclose(self) -> None:
        """Release the provider client used only for compaction."""
        close = getattr(self._client, "aclose", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result


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


@dataclass(frozen=True)
class ModelBudgetMetadata:
    """Resolved model limits used to build a neutral context budget."""

    context_window: int
    output_reserve: int
    window_source: str


DEFAULT_MODEL_CONTEXT_WINDOW = 128_000
DEFAULT_OUTPUT_RESERVE = 4_096
DEFAULT_RESERVE_TOKENS = 16_384


def _resolve_context_budget_metadata(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> ModelBudgetMetadata:
    """Resolve model window/output limits and keep the metadata source visible."""
    from codeagent.app.config import Settings

    resolved_provider = (
        provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    )
    if registry is None:
        registry = _get_default_registry()
    effective_model = model
    if not effective_model:
        defaults = _provider_config(resolved_provider)
        effective_model = getattr(defaults, "model", None)
    base = split_model_pattern(effective_model)[0] if effective_model else None
    if registry is not None and base:
        try:
            spec = registry.resolve(base, provider=resolved_provider)
        except (AttributeError, ValueError):
            spec = None
        if spec is not None:
            context_window = getattr(spec, "context_window", None)
            max_tokens = getattr(spec, "max_tokens", None)
            if type(context_window) is int and context_window > 0:
                output_reserve = (
                    max_tokens
                    if type(max_tokens) is int and max_tokens > 0
                    else DEFAULT_OUTPUT_RESERVE
                )
                return ModelBudgetMetadata(
                    context_window=context_window,
                    output_reserve=min(output_reserve, context_window),
                    window_source="catalog",
                )
    return ModelBudgetMetadata(
        context_window=DEFAULT_MODEL_CONTEXT_WINDOW,
        output_reserve=DEFAULT_OUTPUT_RESERVE,
        window_source="fallback",
    )


def _resolve_context_window(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> int:
    """从模型规格解析上下文窗口,缺失时使用显式 fallback。"""
    return _resolve_context_budget_metadata(
        registry, cfg, provider, model
    ).context_window
