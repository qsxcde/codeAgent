"""openai provider:配置 + 工厂(构造层)。模型目录在 ai/catalog/builtin.py。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from codeagent.ai.catalog.builtin import OPENAI_MODELS
from codeagent.ai.catalog.spec import ModelSpec

if TYPE_CHECKING:
    from codeagent.ai.transport.openai_compat import OpenAICompatClient


class OpenAIConfig(BaseSettings):
    """``OPENAI_`` 前缀环境变量自动映射到字段,如 ``OPENAI_API_KEY``。"""

    model_config = SettingsConfigDict(
        env_prefix="OPENAI_",
        extra="ignore",
    )

    api_key: SecretStr = SecretStr("")  # repr/日志不泄露明文(M7)
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-5-nano"  # 默认模型,用 OPENAI_MODEL 切换
    reasoning_effort: str = "high"


PROVIDER_NAME = "openai"


def make_llm(
    cfg: OpenAIConfig | None = None,
    spec: ModelSpec | None = None,
    *,
    reasoning_effort: str | None = None,
) -> "OpenAICompatClient":
    """按配置 + 模型规格构造自研 ``OpenAICompatClient``。

    未配置 ``api_key`` 时报可操作错误,而不是 OpenAI SDK 的 Missing credentials。
    """
    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    cfg = cfg or OpenAIConfig()
    if not cfg.api_key.get_secret_value():
        raise ValueError(
            "缺少 OPENAI_API_KEY:请在固定配置目录(.codeagent/.env)或环境变量中配置后再创建模型"
        )
    if spec is None:
        spec = OPENAI_MODELS.get(cfg.model) or ModelSpec(id=cfg.model)
    effort = reasoning_effort if reasoning_effort is not None else cfg.reasoning_effort
    return OpenAICompatClient(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=spec.id,
        reasoning_effort=effort if spec.reasoning else None,
        max_tokens=spec.max_tokens,
    )
