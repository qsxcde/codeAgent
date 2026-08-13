"""config 层测试:全局(provider 无关)配置。"""

from codeagent.app.config import Settings, ensure_config_files


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
