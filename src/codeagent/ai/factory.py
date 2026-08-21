"""LLM 统一构造入口:按 provider + model 解析并构造未绑定工具的模型。

- ``PROVIDERS[provider]`` 注册表定义在 ``ai/providers`` 包(provider 名 → 工厂);
- 模型解析(``ModelRegistry``)见 ``ai/catalog/registry.py``;
- 只被组合根(container.py)与测试消费。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeagent.ai.catalog.registry import ModelRegistry
from codeagent.ai.providers import PROVIDERS
from codeagent.app.config import Settings
from codeagent.ai.model_pattern import split_model_pattern

if TYPE_CHECKING:
    from codeagent.ai.protocol.messages import ChatClient

#: 模块级默认注册表缓存:create_llm 不每次重建/重读 models.json(M11)。
_default_registry: "ModelRegistry | None" = None


def _split_pattern(model: str) -> tuple[str, str | None]:
    """``'deepseek-v4-pro:high'`` → ``('deepseek-v4-pro', 'high')``。

    委托共享实现 ``model_pattern.split_model_pattern``。
    """
    return split_model_pattern(model)


def _get_default_registry() -> ModelRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ModelRegistry()
    return _default_registry


def get_available_providers(registry: ModelRegistry) -> list[str]:
    """可用 provider = 模型目录 key ∪ 已注册 provider 工厂 key。

    目录是模型元数据来源,工厂是"能构造"的事实来源;
    两者并集保证 fake 等无目录的 provider 也可被选中(P1-3)。
    放在本层(而非 ModelRegistry):catalog 层不依赖 providers 层。
    """
    return sorted(set(registry.catalog_providers()) | set(PROVIDERS))


def create_llm(
    provider = None,
    model = None,
    *,
    cfg: Settings | None = None,
    reasoning_effort = None,
    registry: ModelRegistry | None = None,
) -> "ChatClient":
    """按 provider + model 解析并构造未绑定工具的模型。

    - ``provider`` 缺省取 ``cfg.llm_provider``;
    - ``model`` 缺省时由供应商工厂用其配置里的默认模型;
    - 思考强度优先级:``model`` 内联后缀(":high") > ``reasoning_effort`` > 供应商配置默认;
    - ``registry`` 可注入(默认模块级缓存一次),不每次重建/重读 models.json(M11);
    - 无模型目录的 provider(如 ``fake``)跳过模型解析直接构造(H11)。
    """
    cfg = cfg or Settings()
    provider = provider or cfg.llm_provider
    if provider not in PROVIDERS:
        raise ValueError(f"未知的 provider: {provider!r},可用: {sorted(PROVIDERS)}")
    registry = registry or _get_default_registry()
    if model:
        base, inline = _split_pattern(model)
        effort = inline or reasoning_effort
        if registry.available(provider):
            spec = registry.resolve(base, provider)
            return PROVIDERS[provider](spec=spec, reasoning_effort=effort)
        # 无目录 provider(fake 等):跳过模型解析直接构造(H11)
        return PROVIDERS[provider](reasoning_effort=effort)
    return PROVIDERS[provider](reasoning_effort=reasoning_effort)
