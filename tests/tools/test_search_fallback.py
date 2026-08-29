"""可选 rg/fd 加速与纯 Python 回退回归。"""

from types import SimpleNamespace
from unittest.mock import patch


def test_grep_uses_rg_json_result_without_changing_context_format(tmp_path) -> None:
    from codeagent.tools.atomic.grep import GrepTool

    target = tmp_path / "src" / "main.py"
    target.parent.mkdir()
    target.write_text("before\nneedle\nafter\n", encoding="utf-8")
    external = SimpleNamespace(
        stdout=(
            b'{"type":"context","data":{"path":{"text":"src/main.py"},'
            b'"line_number":1,"lines":{"text":"before\\n"}}}\n'
            b'{"type":"match","data":{"path":{"text":"src/main.py"},'
            b'"line_number":2,"lines":{"text":"needle\\n"}}}\n'
            b'{"type":"context","data":{"path":{"text":"src/main.py"},'
            b'"line_number":3,"lines":{"text":"after\\n"}}}\n'
        ),
        truncated=False,
    )
    with patch(
        "codeagent.tools.execution.search.run_optional_search", return_value=external
    ) as run:
        result = GrepTool(cwd=str(tmp_path)).invoke(
            GrepTool.Args(pattern="needle", context=1)
        )

    assert "src/main.py-1- before" in result
    assert "src/main.py:2: needle" in result
    assert "src/main.py-3- after" in result
    args = run.call_args.args[1]
    assert "--json" in args
    assert "-C" in args
    assert "needle" in args


def test_grep_falls_back_when_rg_is_unavailable(tmp_path) -> None:
    from codeagent.tools.atomic.grep import GrepTool

    (tmp_path / "main.py").write_text("needle\n", encoding="utf-8")
    with patch("codeagent.tools.execution.search.run_optional_search", return_value=None):
        result = GrepTool(cwd=str(tmp_path)).invoke(
            GrepTool.Args(pattern="needle")
        )

    assert "main.py:1: needle" in result


def test_find_uses_fd_paths_then_reapplies_glob_and_relative_path(tmp_path) -> None:
    from codeagent.tools.atomic.find import FindTool

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("ok", encoding="utf-8")
    external = SimpleNamespace(
        stdout=f"{tmp_path / 'src' / 'main.py'}\0{tmp_path / 'src' / 'main.txt'}\0".encode(),
        truncated=False,
    )
    with patch("codeagent.tools.atomic.find.run_optional_search", return_value=external) as run:
        result = FindTool(cwd=str(tmp_path)).invoke(
            FindTool.Args(pattern="**/*.py")
        )

    assert "src/main.py" in result
    assert "main.txt" not in result
    args = run.call_args.args[1]
    assert "--print0" in args
    assert "--hidden" in args
    assert "--no-ignore" in args


def test_find_falls_back_when_fd_fails(tmp_path) -> None:
    from codeagent.tools.atomic.find import FindTool

    (tmp_path / "main.py").write_text("ok", encoding="utf-8")
    with patch("codeagent.tools.atomic.find.run_optional_search", return_value=None):
        result = FindTool(cwd=str(tmp_path)).invoke(FindTool.Args(pattern="*.py"))

    assert "main.py" in result


def test_optional_search_uses_argv_and_bounded_output(monkeypatch, tmp_path) -> None:
    from codeagent.tools.execution.search import run_optional_search

    seen = {}

    class FakeProcess:
        pid = 123
        returncode = 0

        def wait(self, timeout=None):
            seen["wait_timeout"] = timeout
            return 0

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        output_file = kwargs["stdout"]
        output_file.write(b"one\ntwo\nthree\n")
        output_file.flush()
        return FakeProcess()

    monkeypatch.setattr("shutil.which", lambda name: "/opt/bin/" + name)
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    result = run_optional_search(
        "rg",
        ["--json", "$(touch", "marker)"],
        tmp_path,
        timeout=2,
        max_output_bytes=8,
        cleanup_timeout=0.1,
    )

    assert result.stdout == b"one\ntwo\n"
    assert result.truncated is True
    assert seen["argv"] == ["/opt/bin/rg", "--json", "$(touch", "marker)"]
    assert seen["kwargs"].get("shell", False) is False
    assert seen["wait_timeout"] == 2


def test_optional_search_returns_none_for_failed_or_timed_out_command(
    monkeypatch, tmp_path
) -> None:
    from codeagent.tools.execution.search import run_optional_search
    import subprocess

    class FailedProcess:
        returncode = 2

        def wait(self, timeout=None):
            return 2

    class TimedOutProcess:
        returncode = -9

        def __init__(self):
            self.killed = False

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("rg", timeout)
            return 0

        def kill(self):
            self.killed = True

    processes = iter((FailedProcess(), TimedOutProcess()))
    monkeypatch.setattr("shutil.which", lambda _name: "/opt/bin/rg")
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: next(processes))

    common = {
        "cwd": tmp_path,
        "timeout": 0.01,
        "max_output_bytes": 100,
        "cleanup_timeout": 0.01,
    }
    assert run_optional_search("rg", ["--json"], **common) is None
    assert run_optional_search("rg", ["--json"], **common) is None
