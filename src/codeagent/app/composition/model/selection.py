"""应用组合根中的 provider/model/effort 选择与模型客户端装配。"""

from __future__ import annotations

from typing import Any

from codeagent.ai.catalog.registry import ModelRegistry
from codeagent.ai.catalog.store import ModelStore
from codeagent.ai.model.protocols import ChatClient
from codeagent.ai.providers.all import PROVIDER_CONFIGS, PROVIDERS

KNOWN_EFFORTS = ("low", "medium", "high")
_default_registry: ModelRegistry | None = None


def split_model_pattern(pattern: str) -> tuple[str, str | None]:
    """解析产品输入中的 ``model:effort`` 后缀。"""
    if ":" in pattern:
        base, effort = pattern.rsplit(":", 1)
        if effort in KNOWN_EFFORTS:
            return base, effort
    return pattern, None


def _get_default_registry() -> ModelRegistry:
    global _default_registry
    if _default_registry is None:
        from codeagent.app import config as app_config

        _default_registry = ModelRegistry(ModelStore(app_config.CONFIG_MODELS_FILE))
    return _default_registry


def get_available_providers(registry: ModelRegistry) -> list[str]:
    """返回模型目录 provider 与可构造 provider 的并集。"""
    return sorted(set(registry.catalog_providers()) | set(PROVIDERS))


def _provider_config(provider: str) -> Any | None:
    """由组合根注入固定用户 env 文件，AI provider 本身不读取 app 配置。"""
    config_cls = PROVIDER_CONFIGS.get(provider)
    if config_cls is None:
        return None
    from codeagent.app import config as app_config

    return config_cls(_env_file=app_config.CONFIG_ENV_FILE)


def create_llm(
    provider: str | None = None,
    model: str | None = None,
    *,
    cfg: Any = None,
    reasoning_effort: str | None = None,
    registry: ModelRegistry | None = None,
) -> ChatClient:
    """由组合根读取应用配置并构造未绑定工具的 AI 客户端。"""
    if cfg is None:
        from codeagent.app.config import Settings

        cfg = Settings()
    provider = provider or getattr(cfg, "llm_provider", None)
    if not provider:
        from codeagent.app.config import Settings

        provider = Settings().llm_provider
    if provider not in PROVIDERS:
        raise ValueError(f"未知的 provider: {provider!r},可用: {sorted(PROVIDERS)}")

    registry = registry or _get_default_registry()
    provider_cfg = _provider_config(provider)
    factory = PROVIDERS[provider]
    if model:
        base, inline = split_model_pattern(model)
        effort = inline or reasoning_effort
        if registry.available(provider):
            spec = registry.resolve(base, provider)
            return factory(cfg=provider_cfg, spec=spec, reasoning_effort=effort)
        # fake 等无目录 provider 保持可传入任意模型名的行为。
        return factory(cfg=provider_cfg, reasoning_effort=effort)
    return factory(cfg=provider_cfg, reasoning_effort=reasoning_effort)


__all__ = [
    "KNOWN_EFFORTS",
    "create_llm",
    "get_available_providers",
    "split_model_pattern",
]
