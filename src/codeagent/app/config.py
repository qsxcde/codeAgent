"""应用配置:provider 无关的全局配置。

provider 专属配置各自住在 ``ai/providers/*`` 里(如 ``DeepSeekConfig``)。
只被 ``container.py`` 与 ``ai/`` 读取,核心编排层不得 import 本模块。

配置来源安全(H10):env 文件固定到 home/config 目录,不再读取 CWD 相对路径 ``.env``,
防止在任意仓库内运行 agent 时静默加载该仓库的 ``.env`` 劫持流量与密钥。
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 固定配置目录(env 文件唯一来源,不随 CWD 变化)。
CONFIG_DIR = Path.home() / ".codeagent"
CONFIG_ENV_FILE: Path = CONFIG_DIR / ".env"
CONFIG_MODELS_FILE: Path = CONFIG_DIR / "models.json"
# Skill Package store and persistent metadata (global; project paths are
# derived from ``package_paths`` so tests and alternate workspaces can inject
# their own config/cwd without mutating these constants).
PACKAGE_STORE_DIR: Path = CONFIG_DIR / "packages"
PACKAGE_REGISTRY_FILE: Path = CONFIG_DIR / "registry.json"
PACKAGE_LOCK_FILE: Path = CONFIG_DIR / "skills.lock.json"
#: MCP server 配置(用户级唯一来源;项目级配置不被加载,见 mcp spec)。
CONFIG_MCP_FILE: Path = CONFIG_DIR / "mcp.json"

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


def package_paths(
    cwd: str | Path | None = None,
    *,
    scope: str = "user",
    config_dir: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    """Return ``(store, registry, lock)`` paths for a Skill Package scope."""

    if scope not in {"user", "project"}:
        raise ValueError("Package scope 必须是 user 或 project")
    config = Path(config_dir).expanduser() if config_dir is not None else CONFIG_DIR
    base = config if scope == "user" else Path(cwd or Path.cwd()).expanduser() / ".codeagent"
    return base / "packages", base / "registry.json", base / "skills.lock.json"


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


#: provider → key 环境变量名的约定前缀(与各 provider Config 的 env_prefix 一致):
#: ``deepseek`` → ``DEEPSEEK_API_KEY``。config 层不持有 provider 注册表(防循环
#: import:providers 依赖本模块的 CONFIG_ENV_FILE),故按 provider 名大写推导。
def _api_key_env_name(provider: str) -> str:
    """``deepseek`` → ``DEEPSEEK_API_KEY``(与 provider Config env_prefix 命名一致)。"""
    return f"{provider.upper()}_API_KEY"


def _quote_env_value(value: str) -> str:
    """dotenv 值转义:含 ``#``/``=``/空白/引号时用双引号包裹并转义内部引号。

    保证写回后 python-dotenv 解析结果与原值一致(不因注释符/分隔符截断)。
    """
    if "\n" in value or "\r" in value:
        raise ValueError("API key 不能包含换行符")
    if re.search(r'[\s#"=]', value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def write_env_key(
    provider: str, key: str, env_file: Path | None = None
) -> Path:
    """写入/替换 ``<PROVIDER>_API_KEY`` 到 env 文件(行级,保留注释与其它行)。

    - 键名约定 ``{provider.upper()}_API_KEY``(与 provider Config 的 env_prefix
      一致;未知 provider 名也可写,由调用方保证有效);
    - 原子写:临时文件 + ``os.replace``,防崩溃半写;文件权限收紧 0600
      (Windows 跳过,依赖用户主目录 ACL);
    - 空 key 拒绝(登录流程已拦截空值,此处兜底防御);
    - ``env_file`` 可注入(测试用),缺省 ``CONFIG_ENV_FILE``。
    """
    if not key:
        raise ValueError("API key 不能为空")
    env_file = env_file or CONFIG_ENV_FILE
    env_file.parent.mkdir(parents=True, exist_ok=True)
    target = _api_key_env_name(provider)
    new_line = f"{target}={_quote_env_value(key)}"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{target}="):
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(new_line)
    fd, tmp_name = tempfile.mkstemp(dir=env_file.parent, prefix=".env.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, env_file)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return env_file


def configured_providers(env_file: Path | None = None) -> set[str]:
    """解析 env 文件中已配置非空 key 的 provider 集(如 {"deepseek", "glm"})。

    供 TUI 登录选择器展示已配置标记;只认 ``<NAME>_API_KEY=<非空>`` 行,
    跳过注释与空值;env 文件不存在或不可读时返回空集(不抛错)。
    """
    env_file = env_file or CONFIG_ENV_FILE
    configured: set[str] = set()
    if not env_file.exists():
        return configured
    try:
        content = env_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return configured
    pattern = re.compile(r"^([A-Z][A-Z0-9_]*)_API_KEY=(.+)$")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(stripped)
        if match is None:
            continue
        value = match.group(2).strip().strip('"').strip()
        if value:
            configured.add(match.group(1).lower())
    return configured


class Settings(BaseSettings):
    """全局配置,用固定目录 env 文件或环境变量覆盖默认值。"""

    model_config = SettingsConfigDict(
        env_file=CONFIG_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: str = "deepseek"  # deepseek / openai / fake
    tool_max_concurrency: int = 4
    tool_timeout: float | None = None
    tool_max_timeout: float = 600.0
    tool_max_output_bytes: int = 30_000
    tool_max_output_lines: int = 2_000
    tool_max_memory_bytes: int = 1_048_576
    tool_cleanup_timeout: float = 10.0

    @model_validator(mode="after")
    def _check_cwd_env(self) -> "Settings":
        warn_cwd_env()
        return self
