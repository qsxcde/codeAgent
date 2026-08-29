"""qwen provider:配置 + 工厂(构造层)。模型目录在 ai/catalog/builtin.py。

OpenAI 兼容端点见阿里云百炼文档(2026-08):``dashscope.aliyuncs.com/compatible-mode/v1``。
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from codeagent.ai.catalog.builtin import QWEN_MODELS
from codeagent.ai.catalog.spec import ModelSpec
from codeagent.ai.transport.openai_compat import OpenAICompatClient


class QwenConfig(BaseSettings):
    """``QWEN_`` 前缀环境变量自动映射到字段,如 ``QWEN_API_KEY``。"""

    model_config = SettingsConfigDict(
        env_prefix="QWEN_",
        extra="ignore",
    )

    api_key: SecretStr = SecretStr("")  # repr/日志不泄露明文(M7)
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3.8-max"  # 默认模型,用 QWEN_MODEL 切换
    #: 百炼 OpenAI 兼容层未确认支持 reasoning_effort,默认 None 不发送;
    #: Qwen3 系列模型自身具备 thinking 能力。
    reasoning_effort: str | None = None


PROVIDER_NAME = "qwen"


def make_llm(
    cfg: QwenConfig | None = None,
    spec: ModelSpec | None = None,
    *,
    reasoning_effort: str | None = None,
) -> "OpenAICompatClient":
    """按配置 + 模型规格构造自研 ``OpenAICompatClient``。

    未配置 ``api_key`` 时报可操作错误,而不是 SDK 的 Missing credentials。
    """
    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    cfg = cfg or QwenConfig()
    if not cfg.api_key.get_secret_value():
        raise ValueError(
            "缺少 QWEN_API_KEY:请在固定配置目录(.codeagent/.env)或环境变量中配置后再创建模型"
        )
    if spec is None:
        spec = QWEN_MODELS.get(cfg.model) or ModelSpec(id=cfg.model)
    effort = reasoning_effort if reasoning_effort is not None else cfg.reasoning_effort
    return OpenAICompatClient(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=spec.id,
        provider=PROVIDER_NAME,
        reasoning_effort=effort if spec.reasoning else None,
        max_tokens=spec.max_tokens,
    )
