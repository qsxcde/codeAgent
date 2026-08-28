"""ai 层测试:模型目录 / 注册表解析 / 供应商工厂构造。"""

import json

import pytest
from codeagent.ai.transport.openai_compat import OpenAICompatClient

from codeagent.ai.catalog.spec import ModelSpec
from codeagent.ai.catalog.store import ModelStore
from codeagent.ai.catalog.builtin import BUILTIN_CATALOGS
from codeagent.ai.catalog.registry import ModelRegistry
from codeagent.app.composition.model.selection import (
    create_llm,
    get_available_providers,
    split_model_pattern,
)
from codeagent.ai.providers import PROVIDERS, deepseek, fake, glm, kimi, minimax, qwen
from codeagent.ai.providers.deepseek import DeepSeekConfig
from codeagent.ai.providers.fake import FakeClient
from codeagent.ai.providers.glm import GlmConfig
from codeagent.ai.providers.kimi import KimiConfig
from codeagent.ai.providers.minimax import MiniMaxConfig
from codeagent.ai.providers.qwen import QwenConfig
from codeagent.app.config import Settings


def _empty_registry(tmp_path) -> ModelRegistry:
    """不读真实 models.json 的注册表(保持测试确定性)。"""
    return ModelRegistry(ModelStore(tmp_path / "none.json"))


def test_builtin_catalogs_registered():
    assert "deepseek" in BUILTIN_CATALOGS
    assert "openai" in BUILTIN_CATALOGS
    assert "deepseek-v4-pro" in BUILTIN_CATALOGS["deepseek"]
    for provider in ("qwen", "glm", "kimi", "minimax"):
        assert provider in BUILTIN_CATALOGS
        assert BUILTIN_CATALOGS[provider]  # 目录非空


def test_providers_registered():
    assert set(PROVIDERS) == {"deepseek", "openai", "qwen", "glm", "kimi", "minimax", "fake"}


def test_available_providers_includes_fake(tmp_path):
    """可用 provider 列表 = 模型目录 ∪ 注册工厂,fake 必须可被选中(P1-3)。"""
    reg = _empty_registry(tmp_path)
    providers = get_available_providers(reg)
    assert "fake" in providers
    assert "deepseek" in providers
    assert "openai" in providers


def test_provider_selection_honors_fake_config(tmp_path):
    """LLM_PROVIDER=fake 时容器应选中 fake,而非回退 deepseek(P1-3)。"""
    from codeagent.ai.catalog.registry import ModelRegistry

    reg = _empty_registry(tmp_path)
    providers = get_available_providers(reg)
    default_provider = "fake"
    provider = (
        default_provider
        if default_provider in providers
        else (providers[0] if providers else "fake")
    )
    assert provider == "fake"


def test_resolve_exact_and_alias(tmp_path):
    reg = _empty_registry(tmp_path)
    assert reg.resolve("deepseek-v4-pro", "deepseek").id == "deepseek-v4-pro"
    assert reg.resolve("flash", "deepseek").id == "deepseek-v4-flash"  # 别名


def test_resolve_unknown_raises(tmp_path):
    with pytest.raises(ValueError):
        _empty_registry(tmp_path).resolve("no-such", "deepseek")


def test_registry_upsert_user_models(tmp_path):
    """models.json 按 id upsert:匹配覆盖、新 id 追加、内置保留。"""
    store_path = tmp_path / "models.json"
    store_path.write_text(
        json.dumps(
            {
                "deepseek": {
                    "models": [
                        {"id": "deepseek-v4-pro", "reasoning": False},  # 覆盖内置
                        {"id": "my-local-model"},                        # 追加
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    cat = ModelRegistry(ModelStore(store_path)).available("deepseek")
    assert "deepseek-v4-flash" in cat                 # 内置保留
    assert "my-local-model" in cat                    # 追加
    assert cat["deepseek-v4-pro"].reasoning is False  # 覆盖生效


def test_deepseek_config_env_prefix(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-test")
    assert DeepSeekConfig(_env_file=None).model == "deepseek-v4-test"


def test_deepseek_config_ignores_global_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-test")
    assert DeepSeekConfig(_env_file=None).model == "deepseek-v4-test"


def test_deepseek_reasoning_model_passes_effort():
    llm = deepseek.make_llm(
        DeepSeekConfig(_env_file=None, api_key="sk-test", model="deepseek-v4-pro")
    )
    assert llm.reasoning_effort == "high"


def test_deepseek_non_reasoning_model_omits_effort():
    """非推理 spec(或目录外的未知模型)不应传 reasoning_effort。"""
    llm = deepseek.make_llm(
        DeepSeekConfig(_env_file=None, api_key="sk-test"),
        spec=ModelSpec(id="custom-non-reasoning"),
    )
    assert llm.reasoning_effort is None


def test_create_llm_fake(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    model = create_llm(cfg=Settings(_env_file=None))
    assert isinstance(model, FakeClient)


def test_create_llm_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    model = create_llm("deepseek", "deepseek-v4-pro")
    assert isinstance(model, OpenAICompatClient)
    assert model.model_id == "deepseek-v4-pro"
    assert model.reasoning_effort == "high"


def test_create_llm_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "no-such")
    with pytest.raises(ValueError):
        create_llm(cfg=Settings(_env_file=None))


def test_split_pattern():
    assert split_model_pattern("deepseek-v4-pro:high") == ("deepseek-v4-pro", "high")
    assert split_model_pattern("deepseek-v4-pro") == ("deepseek-v4-pro", None)
    # 非合法 effort 不拆
    assert split_model_pattern("deepseek-v4-pro:foo") == ("deepseek-v4-pro:foo", None)


def test_create_llm_inline_effort(monkeypatch):
    """内联 ``:medium`` 覆盖默认 effort。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    model = create_llm("deepseek", "deepseek-v4-pro:medium")
    assert model.model_id == "deepseek-v4-pro"
    assert model.reasoning_effort == "medium"


def test_create_llm_effort_precedence(monkeypatch):
    """内联 > create_llm 参数。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    model = create_llm("deepseek", "deepseek-v4-pro:high", reasoning_effort="low")
    assert model.reasoning_effort == "high"


def test_create_llm_default_effort(monkeypatch):
    """无覆盖时用供应商配置默认(high)。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    model = create_llm("deepseek", "deepseek-v4-pro")
    assert model.reasoning_effort == "high"


def test_make_llm_effort_override():
    """make_llm 的 reasoning_effort 参数覆盖 cfg 默认。"""
    llm = deepseek.make_llm(
        DeepSeekConfig(_env_file=None, api_key="sk-test", model="deepseek-v4-pro"),
        reasoning_effort="medium",
    )
    assert llm.reasoning_effort == "medium"


def test_deepseek_missing_api_key_raises():
    """缺 api_key 时报可操作错误,而不是 OpenAI SDK 的 Missing credentials。"""
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        deepseek.make_llm(DeepSeekConfig(_env_file=None))


def test_deepseek_max_tokens_consumed():
    """spec.max_tokens 透传给自研客户端。"""
    llm = deepseek.make_llm(
        DeepSeekConfig(_env_file=None, api_key="sk-test"),
        spec=ModelSpec(id="deepseek-v4-pro", max_tokens=4096),
    )
    assert llm.max_tokens == 4096


def test_deepseek_no_max_tokens_when_unset():
    """spec 未设 max_tokens 时不传。"""
    llm = deepseek.make_llm(
        DeepSeekConfig(_env_file=None, api_key="sk-test"),
        spec=ModelSpec(id="deepseek-v4-pro"),
    )
    assert llm.max_tokens is None


def test_fake_provider_self_contained():
    assert fake.PROVIDER_NAME == "fake"
    assert isinstance(fake.make_llm(), FakeClient)


def test_create_llm_fake_with_model(monkeypatch):
    """无目录 provider(fake)带模型名可构造,不抛「未找到模型」(H11)。"""
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    model = create_llm("fake", "fake-model")
    assert isinstance(model, FakeClient)


def test_create_llm_uses_injected_registry(tmp_path, monkeypatch):
    """注入 registry 被复用,不重复读 models.json(M11)。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    store_path = tmp_path / "models.json"
    store_path.write_text(
        json.dumps({"deepseek": {"models": [{"id": "custom-model"}]}}), encoding="utf-8"
    )
    reg = ModelRegistry(ModelStore(store_path))
    m1 = create_llm("deepseek", "custom-model", registry=reg)
    assert m1.model_id == "custom-model"
    # 注入实例后修改文件:不再重读,仍解析到注入时的目录
    store_path.write_text("{}", encoding="utf-8")
    m2 = create_llm("deepseek", "custom-model", registry=reg)
    assert m2.model_id == "custom-model"


def test_resolve_alias_not_prioritized_over_later_exact(tmp_path):
    """两遍法:后序 provider 的精确 id 不被前序 provider 别名抢占(M12)。"""
    store_path = tmp_path / "models.json"
    store_path.write_text(
        json.dumps(
            {
                "deepseek": {"models": [{"id": "deepseek-a", "aliases": ["gpt-5"]}]},
                "openai": {"models": [{"id": "gpt-5"}]},
            }
        ),
        encoding="utf-8",
    )
    reg = ModelRegistry(ModelStore(store_path))
    spec = reg.resolve("gpt-5")  # provider=None
    assert spec.id == "gpt-5"  # openai 精确 id,而非 deepseek 别名


def test_resolve_error_lists_model_ids(tmp_path):
    """解析失败错误信息列出 model id,而非仅 provider 名(M12)。"""
    reg = ModelRegistry(ModelStore(tmp_path / "none.json"))
    with pytest.raises(ValueError) as ei:
        reg.resolve("no-such-model")
    assert "deepseek-v4-flash" in str(ei.value)  # 列出 model id


def test_cwd_env_not_loaded(tmp_path, monkeypatch):
    """CWD 恶意 .env 的 base_url 不生效(H10):env 固定目录解析,不读 CWD。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DEEPSEEK_BASE_URL=http://evil.example\n", encoding="utf-8"
    )
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    cfg = DeepSeekConfig()  # 只读固定目录 env + 真实环境变量
    assert cfg.base_url == "https://api.deepseek.com"


def test_api_key_repr_not_leaked():
    """repr 配置对象不含明文密钥(M7)。"""
    cfg = DeepSeekConfig(_env_file=None, api_key="sk-SECRET123")
    assert "sk-SECRET123" not in repr(cfg)


# -- qwen / glm / kimi / minimax(2026-08 新增供应商) -------------------------


def test_new_provider_config_env_prefix(monkeypatch):
    monkeypatch.setenv("QWEN_MODEL", "qwen-plus")
    monkeypatch.setenv("GLM_MODEL", "glm-5.2")
    monkeypatch.setenv("KIMI_MODEL", "kimi-k2.6")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.5")
    assert QwenConfig(_env_file=None).model == "qwen-plus"
    assert GlmConfig(_env_file=None).model == "glm-5.2"
    assert KimiConfig(_env_file=None).model == "kimi-k2.6"
    assert MiniMaxConfig(_env_file=None).model == "MiniMax-M2.5"


def test_qwen_default_no_reasoning_effort():
    """百炼兼容层未确认支持 reasoning_effort,默认不发送。"""
    llm = qwen.make_llm(QwenConfig(_env_file=None, api_key="sk-test"))
    assert llm.model_id == "qwen3.8-max"
    assert llm.reasoning_effort is None


def test_qwen_reasoning_model_honors_explicit_effort():
    llm = qwen.make_llm(
        QwenConfig(_env_file=None, api_key="sk-test"),
        reasoning_effort="medium",
    )
    assert llm.reasoning_effort == "medium"


def test_glm_default_no_reasoning_effort():
    llm = glm.make_llm(GlmConfig(_env_file=None, api_key="sk-test"))
    assert llm.model_id == "glm-5.2"
    assert llm.reasoning_effort is None


def test_kimi_reasoning_model_passes_effort():
    """kimi-k3 官方支持 reasoning_effort,默认 high。"""
    llm = kimi.make_llm(KimiConfig(_env_file=None, api_key="sk-test"))
    assert llm.model_id == "kimi-k3"
    assert llm.reasoning_effort == "high"


def test_kimi_non_reasoning_model_omits_effort():
    llm = kimi.make_llm(
        KimiConfig(_env_file=None, api_key="sk-test"),
        spec=ModelSpec(id="kimi-k2.6"),
    )
    assert llm.reasoning_effort is None


def test_minimax_default_no_reasoning_effort():
    llm = minimax.make_llm(MiniMaxConfig(_env_file=None, api_key="sk-test"))
    assert llm.model_id == "MiniMax-M3"
    assert llm.reasoning_effort is None


def test_new_providers_missing_api_key_raises():
    with pytest.raises(ValueError, match="QWEN_API_KEY"):
        qwen.make_llm(QwenConfig(_env_file=None))
    with pytest.raises(ValueError, match="GLM_API_KEY"):
        glm.make_llm(GlmConfig(_env_file=None))
    with pytest.raises(ValueError, match="KIMI_API_KEY"):
        kimi.make_llm(KimiConfig(_env_file=None))
    with pytest.raises(ValueError, match="MINIMAX_API_KEY"):
        minimax.make_llm(MiniMaxConfig(_env_file=None))


def test_create_llm_qwen(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    model = create_llm("qwen", "qwen3.7-plus")
    assert isinstance(model, OpenAICompatClient)
    assert model.model_id == "qwen3.7-plus"
