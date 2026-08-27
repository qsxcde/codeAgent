"""内置模型目录(静态数据层,仿 Pi 的 models.generated.ts)。

只放数据,不含任何构造逻辑;新增模型 = 加一行。
模型清单以各供应商 2026-08 官方文档为准;用户可在 models.json 覆盖/追加。
"""

from codeagent.ai.catalog.spec import ModelSpec

DEEPSEEK_MODELS: dict[str, ModelSpec] = {
    "deepseek-v4-flash": ModelSpec(
        id="deepseek-v4-flash", reasoning=True, aliases=["flash"], context_window=256_000
    ),
    "deepseek-v4-pro": ModelSpec(
        id="deepseek-v4-pro", reasoning=True, context_window=256_000
    ),
}

OPENAI_MODELS: dict[str, ModelSpec] = {
    "gpt-5-nano": ModelSpec(id="gpt-5-nano"),
    "gpt-5": ModelSpec(id="gpt-5", reasoning=True),
}

# 阿里云百炼 Model Studio(2026-08):qwen3.8-max 为最新旗舰,Qwen3 系列具备思考能力。
QWEN_MODELS: dict[str, ModelSpec] = {
    "qwen3.8-max": ModelSpec(id="qwen3.8-max", reasoning=True),
    "qwen3.7-plus": ModelSpec(id="qwen3.7-plus", reasoning=True),
    "qwen3.7-flash": ModelSpec(id="qwen3.7-flash", reasoning=True),
    "qwen-max": ModelSpec(id="qwen-max"),
    "qwen-plus": ModelSpec(id="qwen-plus"),
    "qwen-turbo": ModelSpec(id="qwen-turbo"),
    "qwen-long": ModelSpec(id="qwen-long"),
}

# 智谱开放平台(2026-08):glm-5.2 为当前旗舰 Agent 模型。
GLM_MODELS: dict[str, ModelSpec] = {
    "glm-5.2": ModelSpec(id="glm-5.2"),
}

# Kimi / Moonshot(2026-08):kimi-k3 支持 reasoning_effort,上下文 1M;
# kimi-k2.x 系列 256K,按官方文档仅列 kimi-k2.6 与 code-highspeed 变体。
KIMI_MODELS: dict[str, ModelSpec] = {
    "kimi-k3": ModelSpec(id="kimi-k3", reasoning=True, aliases=["kimi"]),
    "kimi-k2.7-code-highspeed": ModelSpec(id="kimi-k2.7-code-highspeed"),
    "kimi-k2.6": ModelSpec(id="kimi-k2.6"),
}

# MiniMax 开放平台(2026-08):OpenAI 兼容端点无需 group_id。
MINIMAX_MODELS: dict[str, ModelSpec] = {
    "MiniMax-M3": ModelSpec(id="MiniMax-M3", reasoning=True),
    "MiniMax-M2.7": ModelSpec(id="MiniMax-M2.7", reasoning=True),
    "MiniMax-M2.5": ModelSpec(id="MiniMax-M2.5"),
    "MiniMax-M2.1": ModelSpec(id="MiniMax-M2.1"),
    "MiniMax-M2": ModelSpec(id="MiniMax-M2"),
    "MiniMax-M2-her": ModelSpec(id="MiniMax-M2-her"),
}

BUILTIN_CATALOGS: dict[str, dict[str, ModelSpec]] = {
    "deepseek": DEEPSEEK_MODELS,
    "openai": OPENAI_MODELS,
    "qwen": QWEN_MODELS,
    "glm": GLM_MODELS,
    "kimi": KIMI_MODELS,
    "minimax": MINIMAX_MODELS,
}

__all__ = [
    "BUILTIN_CATALOGS",
    "DEEPSEEK_MODELS",
    "OPENAI_MODELS",
    "QWEN_MODELS",
    "GLM_MODELS",
    "KIMI_MODELS",
    "MINIMAX_MODELS",
]
