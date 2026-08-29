"""工具资源限制与进程保护回归。"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_resource_limits_validate_and_derive_effective_output_cap() -> None:
    from codeagent.tools.shared import ToolResourceLimits

    limits = ToolResourceLimits.from_config(
        SimpleNamespace(
            tool_max_concurrency=2,
            tool_timeout=1.5,
            tool_max_timeout=3.0,
            tool_max_output_bytes=1024,
            tool_max_output_lines=20,
            tool_max_memory_bytes=128,
            tool_cleanup_timeout=0.25,
        )
    )

    assert limits.max_concurrency == 2
    assert limits.timeout == 1.5
    assert limits.effective_output_bytes == 128
    assert limits.cleanup_timeout == 0.25

    with pytest.raises(ValueError, match="max_concurrency"):
        ToolResourceLimits(max_concurrency=0)
    with pytest.raises(ValueError, match="timeout"):
        ToolResourceLimits(timeout=4, max_timeout=3)


def test_process_runner_never_materializes_more_than_memory_cap(tmp_path) -> None:
    from codeagent.tools.execution import ProcessRequest, ProcessRunner, bash_env, resolve_bash

    try:
        executable = resolve_bash()
    except ValueError:
        pytest.skip("当前平台没有 bash")
    result = ProcessRunner().run(
        ProcessRequest(
            executable=executable,
            command="seq 1 1000",
            cwd=str(tmp_path),
            env=bash_env(),
            timeout=5,
            max_output_bytes=1024,
            max_output_lines=1000,
            max_memory_bytes=32,
        )
    )

    assert result.stdout_shown_bytes <= 32
    assert result.stdout_truncated is True
    assert result.stdout_truncated_by == "tool_memory"
    assert result.stdout_total_bytes > result.stdout_shown_bytes


def test_bash_passes_resource_limits_to_process_request(tmp_path) -> None:
    from codeagent.tools.atomic.bash import BashTool
    from codeagent.tools.shared import ToolResourceLimits

    captured = []

    class StubRunner:
        def run(self, request):
            captured.append(request)
            return SimpleNamespace(
                returncode=0,
                stdout="ok",
                stderr="",
                timed_out=False,
                cleanup_confirmed=True,
                stdout_total_bytes=2,
                stdout_total_lines=1,
                stdout_shown_bytes=2,
                stdout_shown_lines=1,
                stdout_truncated=False,
                stderr_total_bytes=0,
                stderr_total_lines=0,
                stderr_shown_bytes=0,
                stderr_shown_lines=0,
                stderr_truncated=False,
            )

    limits = ToolResourceLimits(
        timeout=2.0,
        max_timeout=4.0,
        max_output_bytes=100,
        max_output_lines=7,
        max_memory_bytes=40,
        cleanup_timeout=0.2,
    )
    with patch("codeagent.tools.atomic.bash.resolve_bash", return_value="/bin/bash"):
        result = BashTool(
            cwd=str(tmp_path), runner=StubRunner(), resource_limits=limits
        ).invoke(BashTool.Args(command="echo ok"))

    assert result
    request = captured[0]
    assert request.timeout == 2.0
    assert request.max_output_bytes == 100
    assert request.max_output_lines == 7
    assert request.max_memory_bytes == 40
    assert request.cleanup_timeout == 0.2


def test_process_timeout_marks_cleanup_uncertain_when_bounded_wait_expires(monkeypatch, tmp_path):
    from codeagent.tools.execution import ProcessRequest, ProcessRunner

    class StuckProcess:
        pid = 123
        returncode = -9

        def wait(self, timeout=None):
            raise __import__("subprocess").TimeoutExpired("bash", timeout)

    class Backend:
        def spawn_kwargs(self, cwd, env):
            return {"cwd": cwd, "env": env}

        def async_spawn_kwargs(self, cwd, env):
            return {"cwd": cwd, "env": env}

        def kill_tree(self, pid):
            return True

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: StuckProcess())
    result = ProcessRunner(Backend()).run(
        ProcessRequest(
            executable="bash",
            command="echo never",
            cwd=str(tmp_path),
            env={},
            timeout=0.01,
            cleanup_timeout=0.001,
        )
    )

    assert result.timed_out is True
    assert result.cleanup_confirmed is False
