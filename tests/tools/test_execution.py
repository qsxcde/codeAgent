"""execution 子包的跨平台进程契约测试。"""

from __future__ import annotations

import asyncio
import subprocess

import pytest

from codeagent.tools.execution import ProcessRequest, ProcessRunner, bash_env, resolve_bash
from codeagent.tools.execution.posix import PosixProcessBackend
from codeagent.tools.execution.windows import WindowsProcessBackend


def test_process_request_and_result_boundary(tmp_path):
    try:
        executable = resolve_bash()
    except ValueError:
        pytest.skip("当前平台没有 bash")
    request = ProcessRequest(
        executable=executable,
        command="printf output; printf error >&2",
        cwd=str(tmp_path),
        env=bash_env(),
        timeout=5,
    )
    result = ProcessRunner().run(request)
    assert result.returncode == 0
    assert result.stdout == "output"
    assert result.stderr == "error"
    assert result.timed_out is False
    assert result.cleanup_confirmed is True


def test_process_runner_bounds_captured_output_and_reports_totals(tmp_path):
    try:
        executable = resolve_bash()
    except ValueError:
        pytest.skip("当前平台没有 bash")
    request = ProcessRequest(
        executable=executable,
        command="seq 1 100",
        cwd=str(tmp_path),
        env=bash_env(),
        timeout=5,
        max_output_bytes=64,
        max_output_lines=3,
    )

    result = ProcessRunner().run(request)

    assert "1" in result.stdout and "3" in result.stdout
    assert "100" not in result.stdout
    assert result.stdout_total_lines == 100
    assert result.stdout_total_bytes > result.stdout_shown_bytes
    assert result.stdout_truncated is True


async def test_process_runner_async_uses_same_result_contract(tmp_path):
    try:
        executable = resolve_bash()
    except ValueError:
        pytest.skip("当前平台没有 bash")
    request = ProcessRequest(executable, "printf async", str(tmp_path), bash_env(), 5)
    result = await (ProcessRunner().arun(request))
    assert (result.returncode, result.stdout, result.stderr) == (0, "async", "")


def test_process_runner_timeout_uses_portable_python_scenario(tmp_path):
    """超时场景不依赖 Unix ``sleep`` 命令,Windows/Linux/macOS 均可复现。"""
    try:
        executable = resolve_bash()
    except ValueError:
        pytest.skip("当前平台没有 bash")

    request = ProcessRequest(
        executable=executable,
        command='python -c "import time; time.sleep(5)"',
        cwd=str(tmp_path),
        env=bash_env(),
        timeout=1,
    )
    result = ProcessRunner().run(request)

    assert result.timed_out is True
    assert isinstance(result.cleanup_confirmed, bool)


def test_posix_backend_creates_new_process_session_and_kill_group():
    backend = PosixProcessBackend()
    assert backend.spawn_kwargs("/tmp", {"PATH": "/bin"}) == {
        "cwd": "/tmp",
        "env": {"PATH": "/bin"},
        "start_new_session": True,
    }


def test_windows_backend_declares_process_group_and_cleanup_uncertainty(monkeypatch):
    group_flag = 0x00000200
    no_window_flag = 0x08000000
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", group_flag, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", no_window_flag, raising=False)
    backend = WindowsProcessBackend()
    kwargs = backend.spawn_kwargs("C:\\work", {"Path": "C:\\bin"})
    assert kwargs["cwd"] == "C:\\work"
    assert kwargs["env"] == {"Path": "C:\\bin"}
    assert kwargs["creationflags"] == group_flag | no_window_flag
    assert backend.kill_tree(12345) is False
