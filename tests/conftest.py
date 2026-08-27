"""pytest 共享夹具。"""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

pytest_plugins = (
    "tests.fixtures.ai",
    "tests.fixtures.filesystem",
    "tests.fixtures.resources",
    "tests.fixtures.session",
    "tests.fixtures.tui",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """给每个测试分配一个主分类，并补充必要的横切标签。

    主分类默认是 ``unit``，只有明确跨越运行时边界的测试才升级为
    contract/integration/e2e/performance。这样新增测试不会因为忘记写
    marker 而从分层命令中消失；平台和安全标签作为附加分类保留。
    """
    for item in items:
        path = item.path.as_posix().lower()
        name = item.name.lower()

        if path.endswith("tests/tui/test_performance.py") or "performance" in name:
            primary = "performance"
            item.add_marker(pytest.mark.slow)
        elif path.endswith("tests/test_cli.py") or path.endswith("tests/test_main_cli_usage.py"):
            primary = "e2e"
        elif "/tests/app/" in path or "/tests/mcp/" in path or path.endswith("tests/test_container.py"):
            primary = "integration"
        elif (
            "boundar" in path
            or "contract" in path
            or path.endswith("tests/test_decoupling.py")
        ):
            primary = "contract"
        else:
            primary = "unit"

        item.add_marker(getattr(pytest.mark, primary))

        if "/tests/tools/" in path and (
            path.endswith("test_execution.py") or path.endswith("test_tools.py")
        ):
            item.add_marker(pytest.mark.platform)
        if path.endswith("tests/tools/test_security.py"):
            item.add_marker(pytest.mark.security)
        if any(
            token in path
            for token in (
                "test_import_boundaries.py",
                "test_ai_import_boundaries.py",
                "test_runtime_boundaries.py",
                "test_store_modules.py",
            )
        ):
            item.add_marker(pytest.mark.compatibility)


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """把 ensure_config_files 的写入位置重定向到临时目录。

    避免走启动路径的测试(container/session_client)在用户真实
    ``~/.codeagent`` 里生成模板文件;读取路径(Settings/ModelStore)
    仍只读,无副作用。
    """
    import codeagent.app.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".codeagent")


@pytest_asyncio.fixture(autouse=True)
async def _assert_async_tasks_are_clean() -> None:
    """Cancel and report tasks that escape an async test."""
    yield

    current = asyncio.current_task()
    leaked = [
        task
        for task in asyncio.all_tasks()
        if task is not current and not task.done()
    ]
    if not leaked:
        return

    details = ", ".join(
        task.get_name() or repr(task.get_coro()) for task in leaked
    )
    for task in leaked:
        task.cancel()
    await asyncio.gather(*leaked, return_exceptions=True)
    pytest.fail(f"async test leaked pending task(s): {details}")
