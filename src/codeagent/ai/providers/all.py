"""内置 provider 的显式集合。"""

from __future__ import annotations

from codeagent.ai.providers import deepseek, fake, glm, kimi, minimax, openai, qwen
from codeagent.ai.providers.base import ProviderDefinition, ProviderFactory

BUILTIN_PROVIDERS: tuple[ProviderDefinition, ...] = tuple(
    ProviderDefinition(provider_id=module.PROVIDER_NAME, factory=module.make_llm)
    for module in (deepseek, openai, qwen, glm, kimi, minimax, fake)
)

PROVIDERS: dict[str, ProviderFactory] = {
    definition.provider_id: definition.factory for definition in BUILTIN_PROVIDERS
}

PROVIDER_CONFIGS: dict[str, type] = {
    deepseek.PROVIDER_NAME: deepseek.DeepSeekConfig,
    openai.PROVIDER_NAME: openai.OpenAIConfig,
    qwen.PROVIDER_NAME: qwen.QwenConfig,
    glm.PROVIDER_NAME: glm.GlmConfig,
    kimi.PROVIDER_NAME: kimi.KimiConfig,
    minimax.PROVIDER_NAME: minimax.MiniMaxConfig,
}

__all__ = ["BUILTIN_PROVIDERS", "PROVIDER_CONFIGS", "PROVIDERS"]
