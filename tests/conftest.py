"""pytest 共享夹具。"""

import pytest

from codeagent.ai.providers import FakeClient
from codeagent.app.config import Settings


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """把 ensure_config_files 的写入位置重定向到临时目录。

    避免走启动路径的测试(container/session_client)在用户真实
    ``~/.codeagent`` 里生成模板文件;读取路径(Settings/ModelStore)
    仍只读,无副作用。
    """
    import codeagent.app.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".codeagent")


@pytest.fixture
def fake_model() -> FakeClient:
    """离线假模型,默认返回固定文本。"""
    return FakeClient(response="测试回复")


@pytest.fixture
def settings() -> Settings:
    """不读 `.env`,保持测试确定性(用环境变量或默认值)。"""
    return Settings(_env_file=None)
