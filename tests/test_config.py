"""config 层测试:全局(provider 无关)配置。"""

import os

import pytest

from codeagent.app.config import (
    Settings,
    configured_providers,
    ensure_config_files,
    write_env_key,
)


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.llm_provider == "deepseek"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert Settings(_env_file=None).llm_provider == "fake"


def test_settings_ignores_provider_env(monkeypatch):
    """provider 专属键(DEEPSEEK_* 等)不应污染全局 Settings。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-test")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    s = Settings(_env_file=None)
    assert s.llm_provider == "fake"


# -- ensure_config_files(首次启动自动生成配置模板) --------------------------


def test_ensure_config_files_creates_templates(tmp_path):
    """首次调用生成目录 + .env / models.json 模板。"""
    created = ensure_config_files(tmp_path)
    assert sorted(p.name for p in created) == [".env", "models.json"]

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert env.startswith("# codeagent 配置")
    assert "LLM_PROVIDER=deepseek" in env
    assert "DEEPSEEK_API_KEY=" in env
    assert (tmp_path / "models.json").exists()


def test_ensure_config_files_never_overwrites_existing(tmp_path):
    """已存在的文件绝不覆盖(用户配置优先);缺失的模板仍会补齐。"""
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=fake\n", encoding="utf-8")

    created = ensure_config_files(tmp_path)
    assert [p.name for p in created] == ["models.json"]  # .env 已存在不生成
    assert env.read_text(encoding="utf-8") == "LLM_PROVIDER=fake\n"  # 内容未被覆盖

    # 再次调用:全部存在,零创建(幂等)
    assert ensure_config_files(tmp_path) == []


# -- write_env_key / configured_providers(/login 写回,tui-login-command) ----


def test_write_env_key_replaces_existing(tmp_path):
    """已存在键 → 行级替换,注释与其它行保留。"""
    env = tmp_path / ".env"
    env.write_text(
        "# 注释\nLLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=old\nDEEPSEEK_MODEL=deepseek-v4-flash\n",
        encoding="utf-8",
    )
    write_env_key("deepseek", "sk-new", env)
    content = env.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-new" in content
    assert "DEEPSEEK_API_KEY=old" not in content
    assert "LLM_PROVIDER=deepseek" in content
    assert content.startswith("# 注释")


def test_write_env_key_appends_when_missing(tmp_path):
    """键不存在 → 追加到文件末尾,不动其它行。"""
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=deepseek\n", encoding="utf-8")
    write_env_key("glm", "sk-glm", env)
    content = env.read_text(encoding="utf-8")
    assert "GLM_API_KEY=sk-glm" in content
    assert "LLM_PROVIDER=deepseek" in content


def test_write_env_key_quotes_special_values(tmp_path):
    """值含 # / = / 空白 → 双引号包裹,保证 dotenv 回读一致。"""
    env = tmp_path / ".env"
    write_env_key("deepseek", "sk-a#b=c d", env)
    assert 'DEEPSEEK_API_KEY="sk-a#b=c d"' in env.read_text(encoding="utf-8")


def test_write_env_key_creates_file_with_0600(tmp_path):
    """缺失文件 → 自动创建目录与文件,权限 0600(Windows 跳过)。"""
    env = tmp_path / "nested" / ".env"
    write_env_key("openai", "sk-x", env)
    assert env.exists()
    if os.name != "nt":
        assert (env.stat().st_mode & 0o777) == 0o600


def test_write_env_key_rejects_empty(tmp_path):
    """空 key → ValueError(登录流程已拦截,此处兜底)。"""
    with pytest.raises(ValueError):
        write_env_key("deepseek", "", tmp_path / ".env")


def test_write_env_key_unwritable_location(tmp_path):
    """写入位置不可用(父路径被文件占位)→ OSError 原样上抛,不吞错。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        write_env_key("deepseek", "sk-x", blocker / ".env")


def test_configured_providers_parses_nonempty_keys(tmp_path):
    """只认 <NAME>_API_KEY=<非空>:跳过注释、空值与带引号空值。"""
    env = tmp_path / ".env"
    env.write_text(
        "# 注释\nLLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=sk-1\nDEEPSEEK_MODEL=x\n"
        'GLM_API_KEY=""\nOPENAI_API_KEY=\nKIMI_API_KEY="sk-2"\n',
        encoding="utf-8",
    )
    assert configured_providers(env) == {"deepseek", "kimi"}


def test_configured_providers_missing_file(tmp_path):
    """env 文件不存在 → 空集,不抛错。"""
    assert configured_providers(tmp_path / ".env") == set()
