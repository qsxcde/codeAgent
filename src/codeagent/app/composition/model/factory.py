"""模型组合根。

客户端端口适配与上下文预算解析已拆到专责模块。
"""

from __future__ import annotations

from typing import Any

from codeagent.ai.model.types import ChatMessage

from . import budget as _model_budget
from .budget import (
    DEFAULT_MODEL_CONTEXT_WINDOW,
    DEFAULT_OUTPUT_RESERVE,
    DEFAULT_RESERVE_TOKENS,
    ModelBudgetMetadata,
    fit_budget_reserves as _fit_budget_reserves,
)
from .port import (
    ChatModelPort,
    parse_tool_arguments as _parse_tool_arguments,
    to_chat_message as _to_chat_message,
    usage_of as _usage_of,
)
from .selection import _get_default_registry, _provider_config, split_model_pattern

__all__ = [
    "ChatModelPort",
    "LlmSummarizer",
    "ModelBudgetMetadata",
    "_fit_budget_reserves",
    "_parse_tool_arguments",
    "_resolve_context_budget_metadata",
    "_resolve_context_window",
    "_resolve_model_effort",
    "_to_chat_message",
    "_usage_of",
]


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

    async def summarize(self, messages: list[Any], prev_summary: str | None) -> str:
        history = "\n".join(
            f"{message.role}: {message.content}"
            for message in messages
            if getattr(message, "content", "")
        )
        prompt = self._PROMPT.format(history=history, prev=prev_summary or "(无)")
        response = await self._client.generate(
            [
                ChatMessage(role="system", content=self._SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt),
            ],
            tools=None,
        )
        return str(response.content or "")

    async def aclose(self) -> None:
        """释放只用于压缩的 provider 客户端。"""
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
    """解析 model / effort：内联后缀优先于显式 effort 和 provider 默认。"""
    from codeagent.app.config import Settings

    provider = provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    base, inline = split_model_pattern(model) if model else (None, None)
    effort = inline or reasoning_effort
    defaults = _provider_config(provider)
    if defaults is not None:
        base = base or defaults.model
        effort = effort or defaults.reasoning_effort
    return base or "", effort or ""


def _resolve_context_budget_metadata(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> ModelBudgetMetadata:
    """供组合根替换的预算解析入口。"""
    effective_registry = registry if registry is not None else _get_default_registry()
    effective_model = model
    if not effective_model:
        from codeagent.app.config import Settings

        resolved_provider = provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
        defaults = _provider_config(resolved_provider)
        effective_model = getattr(defaults, "model", None)
    return _model_budget.resolve_context_budget_metadata(
        effective_registry, cfg, provider, effective_model
    )


def _resolve_context_window(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> int:
    return _resolve_context_budget_metadata(registry, cfg, provider, model).context_window
