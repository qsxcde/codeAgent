"""glm provider:配置 + 工厂(构造层)。模型目录在 ai/catalog/builtin.py。

OpenAI 兼容端点见智谱开放平台文档(2026-08):``open.bigmodel.cn/api/paas/v4``。
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from codeagent.ai.catalog.builtin import GLM_MODELS
from codeagent.ai.catalog.spec import ModelSpec
from codeagent.ai.transport.openai_compat import OpenAICompatClient


class GlmConfig(BaseSettings):
    """``GLM_`` 前缀环境变量自动映射到字段,如 ``GLM_API_KEY``。"""

    model_config = SettingsConfigDict(
        env_prefix="GLM_",
        extra="ignore",
    )

    api_key: SecretStr = SecretStr("")  # repr/日志不泄露明文(M7)
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-5.2"  # 默认模型,用 GLM_MODEL 切换
    #: 文档未确认 OpenAI 兼容层支持 reasoning_effort,默认 None 不发送。
    reasoning_effort: str | None = None


PROVIDER_NAME = "glm"


def make_llm(
    cfg: GlmConfig | None = None,
    spec: ModelSpec | None = None,
    *,
    reasoning_effort: str | None = None,
) -> "OpenAICompatClient":
    """按配置 + 模型规格构造自研 ``OpenAICompatClient``。

    未配置 ``api_key`` 时报可操作错误,而不是 SDK 的 Missing credentials。
    """
    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    cfg = cfg or GlmConfig()
    if not cfg.api_key.get_secret_value():
        raise ValueError(
            "缺少 GLM_API_KEY:请在固定配置目录(.codeagent/.env)或环境变量中配置后再创建模型"
        )
    if spec is None:
        spec = GLM_MODELS.get(cfg.model) or ModelSpec(id=cfg.model)
    effort = reasoning_effort if reasoning_effort is not None else cfg.reasoning_effort
    return OpenAICompatClient(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=spec.id,
        reasoning_effort=effort if spec.reasoning else None,
        max_tokens=spec.max_tokens,
    )
