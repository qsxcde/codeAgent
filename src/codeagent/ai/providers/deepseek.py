"""deepseek provider:配置 + 工厂(构造层)。模型目录在 ai/catalog/builtin.py。"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from codeagent.ai.catalog.builtin import DEEPSEEK_MODELS
from codeagent.ai.catalog.spec import ModelSpec
from codeagent.app.config import CONFIG_ENV_FILE


class DeepSeekConfig(BaseSettings):
    """``DEEPSEEK_`` 前缀环境变量自动映射到字段,如 ``DEEPSEEK_API_KEY``。"""

    model_config = SettingsConfigDict(
        env_prefix="DEEPSEEK_",
        env_file=CONFIG_ENV_FILE,  # 固定 home/config 目录,不读 CWD .env(H10)
        extra="ignore",
    )

    api_key: SecretStr = SecretStr("")  # repr/日志不泄露明文(M7)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"  # 默认模型,用 DEEPSEEK_MODEL 切换
    reasoning_effort: str = "high"


PROVIDER_NAME = "deepseek"


def make_llm(
    cfg: DeepSeekConfig | None = None,
    spec: ModelSpec | None = None,
    *,
    reasoning_effort: str | None = None,
) -> "OpenAICompatClient":
    """按配置 + 模型规格构造自研 ``OpenAICompatClient``。

    - ``spec`` 缺省时按 ``cfg.model`` 在内置目录解析;查不到的新模型按非推理处理;
    - ``reasoning_effort`` 缺省时用 ``cfg.reasoning_effort``(单次覆盖 > 配置默认),
      原样透传给供应商(不再被 langchain SDK 抹平);
    - 未配置 ``api_key`` 时报可操作错误,而不是 SDK 的 Missing credentials。
    """
    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    cfg = cfg or DeepSeekConfig()
    if not cfg.api_key.get_secret_value():
        raise ValueError(
            "缺少 DEEPSEEK_API_KEY:请在固定配置目录(.codeagent/.env)或环境变量中配置后再创建模型"
        )
    if spec is None:
        spec = DEEPSEEK_MODELS.get(cfg.model) or ModelSpec(id=cfg.model)
    effort = reasoning_effort if reasoning_effort is not None else cfg.reasoning_effort
    return OpenAICompatClient(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=spec.id,
        reasoning_effort=effort if spec.reasoning else None,
        max_tokens=spec.max_tokens,
    )
