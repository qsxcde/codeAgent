"""应用配置:provider 无关的全局配置。

provider 专属配置各自住在 ``ai/providers/*`` 里(如 ``DeepSeekConfig``)。
只被 ``container.py`` 与 ``ai/`` 读取,核心编排层不得 import 本模块。

配置来源安全(H10):env 文件固定到 home/config 目录,不再读取 CWD 相对路径 ``.env``,
防止在任意仓库内运行 agent 时静默加载该仓库的 ``.env`` 劫持流量与密钥。
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 固定配置目录(env 文件唯一来源,不随 CWD 变化)。
CONFIG_DIR = Path.home() / ".codeagent"
CONFIG_ENV_FILE: Path = CONFIG_DIR / ".env"
CONFIG_MODELS_FILE: Path = CONFIG_DIR / "models.json"

#: 一次性告警标志:CWD .env 迁移提示只打一次。
_cwd_env_warned = False

#: 首次启动生成的 .env 模板(空值占位,用户填充后重启生效)。
_ENV_TEMPLATE = """\
# codeagent 配置(首次启动自动生成;填入密钥/端点后重启生效)
# 全局:选 provider(deepseek / openai / qwen / glm / kimi / minimax / fake)
LLM_PROVIDER=deepseek

# DeepSeek(DEEPSEEK_ 前缀自动映射到 DeepSeekConfig)
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_REASONING_EFFORT=high

# OpenAI(OPENAI_ 前缀)
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5-nano
OPENAI_REASONING_EFFORT=high

# 通义千问(QWEN_ 前缀)/ 智谱(GLM_ 前缀)/ Kimi(KIMI_ 前缀)/ MiniMax(MINIMAX_ 前缀)
# 结构相同: *_API_KEY / *_BASE_URL / *_MODEL / *_REASONING_EFFORT
"""

#: 首次启动生成的 models.json 模板(按 id 与内置目录 upsert 合并)。
_MODELS_JSON_TEMPLATE = """\
{
  "deepseek": {
    "models": [
      {
        "id": "deepseek-v4-pro",
        "reasoning": true,
        "maxTokens": 8192,
        "aliases": ["pro"]
      }
    ]
  }
}
"""


def ensure_config_files(cfg_dir: Path | None = None) -> list[Path]:
    """确保固定配置目录与模板文件存在(幂等,不覆盖已有内容)。

    - 首次启动自动创建 ``~/.codeagent/`` 目录与 ``.env`` / ``models.json`` 模板,
      供用户填充密钥与自定义模型;已存在的文件**绝不覆盖**(用户配置优先);
    - 创建失败仅告警,不阻塞启动(纯读取路径仍可正常运行);
    - ``cfg_dir`` 可注入(测试用),缺省为 ``CONFIG_DIR``。
    """
    cfg_dir = cfg_dir or CONFIG_DIR
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logging.warning("无法创建配置目录 %s(已跳过): %s", cfg_dir, exc)
        return []
    created: list[Path] = []
    for path, template in (
        (cfg_dir / ".env", _ENV_TEMPLATE),
        (cfg_dir / "models.json", _MODELS_JSON_TEMPLATE),
    ):
        try:
            if not path.exists():
                path.write_text(template, encoding="utf-8")
                created.append(path)
        except OSError as exc:
            logging.warning("无法生成配置文件 %s(已跳过): %s", path, exc)
    if created:
        logging.info("已生成配置模板: %s(请填写密钥后重启生效)", ", ".join(map(str, created)))
    return created


def warn_cwd_env() -> None:
    """CWD 存在含配置键的 .env 时告警,提示迁移到固定目录(一次性)。"""
    global _cwd_env_warned
    if _cwd_env_warned:
        return
    cwd_env = Path(".env")
    if not cwd_env.exists():
        return
    try:
        content = cwd_env.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    if not any(k in content for k in ("LLM_PROVIDER=", "DEEPSEEK_", "OPENAI_")):
        return
    _cwd_env_warned = True
    logging.warning(
        "检测到当前目录存在 .env(含 codeagent 配置键);codeagent 不再读取 CWD 的 "
        ".env,请将密钥/端点迁移到 %s。",
        CONFIG_ENV_FILE,
    )


class Settings(BaseSettings):
    """全局配置,用固定目录 env 文件或环境变量覆盖默认值。"""

    model_config = SettingsConfigDict(
        env_file=CONFIG_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: str = "deepseek"  # deepseek / openai / fake

    @model_validator(mode="after")
    def _check_cwd_env(self) -> "Settings":
        warn_cwd_env()
        return self
