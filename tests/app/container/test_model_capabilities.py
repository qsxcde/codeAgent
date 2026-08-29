"""模型能力快照组合根契约测试。"""

from codeagent.ai.catalog.registry import ModelRegistry
from codeagent.ai.catalog.spec import ModelSpec
from codeagent.app.composition.model.capabilities import (
    resolve_model_capabilities,
)


def test_resolver_uses_catalog_facts_and_keeps_cache_observation_separate():
    registry = ModelRegistry()
    registry._catalogs.setdefault("fake", {})["declared"] = ModelSpec(
        id="declared",
        reasoning=True,
        tool_calling=False,
        prompt_cache=True,
        context_window=40_000,
    )

    capabilities = resolve_model_capabilities(registry, None, "fake", "declared:high")
    observed = capabilities.with_cache_observation(12)

    assert capabilities.model == "declared"
    assert capabilities.context_window == 40_000
    assert capabilities.window_source == "catalog"
    assert capabilities.reasoning is True
    assert capabilities.tool_calling is False
    assert capabilities.prompt_cache is True
    assert capabilities.cached_tokens_observed is None
    assert observed.cached_tokens_observed == 12
    assert observed.prompt_cache is True


def test_resolver_marks_missing_catalog_facts_unknown_and_uses_fallback_window():
    capabilities = resolve_model_capabilities(ModelRegistry(), None, "fake", "unlisted")

    assert capabilities.model == "unlisted"
    assert capabilities.context_window == 128_000
    assert capabilities.window_source == "fallback"
    assert capabilities.reasoning is None
    assert capabilities.tool_calling is None
    assert capabilities.prompt_cache is None
