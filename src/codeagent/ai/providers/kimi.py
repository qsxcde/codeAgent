"""kimi provider:配置 + 工厂(构造层)。模型目录在 ai/catalog/builtin.py。

OpenAI 兼容端点见 Kimi(月之暗面 Moonshot)文档(2026-08):``api.moonshot.cn/v1``;
``kimi-k3`` 支持 ``reasoning_effort`` 参数。
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from codeagent.ai.catalog.builtin import KIMI_MODELS
from codeagent.ai.catalog.spec import ModelSpec
from codeagent.ai.transport.openai_compat import OpenAICompatClient


class KimiConfig(BaseSettings):
    """``KIMI_`` 前缀环境变量自动映射到字段,如 ``KIMI_API_KEY``。"""

    model_config = SettingsConfigDict(
        env_prefix="KIMI_",
        extra="ignore",
    )

    api_key: SecretStr = SecretStr("")  # repr/日志不泄露明文(M7)
    base_url: str = "https://api.moonshot.cn/v1"
    model: str = "kimi-k3"  # 默认模型,用 KIMI_MODEL 切换
    reasoning_effort: str = "high"


PROVIDER_NAME = "kimi"


def make_llm(
    cfg: KimiConfig | None = None,
    spec: ModelSpec | None = None,
    *,
    reasoning_effort: str | None = None,
) -> "OpenAICompatClient":
    """按配置 + 模型规格构造自研 ``OpenAICompatClient``。

    未配置 ``api_key`` 时报可操作错误,而不是 SDK 的 Missing credentials。
    """
    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    cfg = cfg or KimiConfig()
    if not cfg.api_key.get_secret_value():
        raise ValueError(
            "缺少 KIMI_API_KEY:请在固定配置目录(.codeagent/.env)或环境变量中配置后再创建模型"
        )
    if spec is None:
        spec = KIMI_MODELS.get(cfg.model) or ModelSpec(id=cfg.model)
    effort = reasoning_effort if reasoning_effort is not None else cfg.reasoning_effort
    return OpenAICompatClient(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=spec.id,
        provider=PROVIDER_NAME,
        reasoning_effort=effort if spec.reasoning else None,
        max_tokens=spec.max_tokens,
    )
