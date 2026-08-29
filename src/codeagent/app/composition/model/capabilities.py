"""模型能力元数据的组合根投影。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from .budget import resolve_context_budget_metadata
from .selection import _get_default_registry, _provider_config, split_model_pattern

CapabilityState = Literal["supported", "unsupported", "unknown"]


@dataclass(frozen=True)
class ModelCapabilities:
    """当前模型的只读能力快照。

    ``None`` 表示没有可靠的静态或适配器事实;它和 ``False`` 有意保持不同。
    ``cached_tokens_observed`` 是运行期 usage 观测,不是模型能力声明。
    """

    provider: str = ""
    model: str = ""
    context_window: int | None = None
    window_source: str = "unknown"
    reasoning: bool | None = None
    tool_calling: bool | None = None
    prompt_cache: bool | None = None
    cached_tokens_observed: int | None = None

    def with_cache_observation(self, cached_tokens: int | None) -> "ModelCapabilities":
        """返回带本次会话缓存 usage 观测的副本,不改变能力声明。"""
        return replace(self, cached_tokens_observed=cached_tokens)


def capability_state(value: bool | None) -> CapabilityState:
    """将三态布尔值映射到稳定的诊断状态名。"""
    if value is True:
        return "supported"
    if value is False:
        return "unsupported"
    return "unknown"


def resolve_model_capabilities(
    registry: Any,
    cfg: Any,
    provider: str | None,
    model: str | None,
) -> ModelCapabilities:
    """从当前选择解析模型能力,不访问网络或执行模型请求。"""
    from codeagent.app.config import Settings

    resolved_provider = (
        provider
        or getattr(cfg, "llm_provider", None)
        or Settings().llm_provider
    )
    effective_model = model
    if not effective_model:
        defaults = _provider_config(resolved_provider)
        effective_model = getattr(defaults, "model", None)
    model_id = split_model_pattern(effective_model)[0] if effective_model else ""

    effective_registry = registry if registry is not None else _get_default_registry()
    spec = None
    if model_id:
        try:
            spec = effective_registry.resolve(model_id, provider=resolved_provider)
        except (AttributeError, ValueError):
            spec = None

    budget = resolve_context_budget_metadata(
        effective_registry, cfg, resolved_provider, model_id or None
    )
    return ModelCapabilities(
        provider=resolved_provider,
        model=model_id,
        context_window=budget.context_window,
        window_source=budget.window_source,
        reasoning=getattr(spec, "reasoning", None),
        tool_calling=getattr(spec, "tool_calling", None),
        prompt_cache=getattr(spec, "prompt_cache", None),
    )


__all__ = [
    "CapabilityState",
    "ModelCapabilities",
    "capability_state",
    "resolve_model_capabilities",
]
