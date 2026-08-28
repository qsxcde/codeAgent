"""模型上下文窗口和请求预留的解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .selection import _get_default_registry, _provider_config, split_model_pattern

DEFAULT_MODEL_CONTEXT_WINDOW = 128_000
DEFAULT_OUTPUT_RESERVE = 4_096
DEFAULT_RESERVE_TOKENS = 16_384


def fit_budget_reserves(
    context_window: int,
    output_reserve: int,
    reserve_tokens: int,
) -> tuple[int, int]:
    """把可选预留限制在有效的正上下文窗口内。"""
    if type(context_window) is not int or context_window < 1:
        return output_reserve, reserve_tokens
    if type(output_reserve) is int and output_reserve >= 0:
        output_reserve = min(output_reserve, context_window)
    if type(reserve_tokens) is int and reserve_tokens >= 0:
        remaining = max(0, context_window - output_reserve)
        reserve_tokens = min(reserve_tokens, remaining)
    return output_reserve, reserve_tokens


@dataclass(frozen=True)
class ModelBudgetMetadata:
    """构建中立上下文预算所需的模型限制。"""

    context_window: int
    output_reserve: int
    window_source: str


def resolve_context_budget_metadata(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> ModelBudgetMetadata:
    """解析模型窗口/输出限制，并保留元数据来源。"""
    from codeagent.app.config import Settings

    resolved_provider = provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
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


def resolve_context_window(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> int:
    """解析上下文窗口，缺失时使用显式 fallback。"""
    return resolve_context_budget_metadata(registry, cfg, provider, model).context_window
