from __future__ import annotations

import asyncio
from pathlib import Path

from codeagent.app.task_modes import TaskMode
from codeagent.app.task_supervisor import TaskSupervisor
from codeagent.app.task_verification import TaskStatus, VerificationResult


class FakeSession:
    def __init__(self, action=None):
        self.action = action
        self.calls = []
        self.last_failure = None

    async def run(self, text, *, policy=None):
        self.calls.append((text, policy))
        if self.action:
            self.action(text)

    def abort(self):
        pass


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def run(self, command, *, source="explicit", timeout=None):
        self.calls.append(command)
        return self.results.pop(0)


def test_supervisor_does_not_verify_without_workspace_changes(tmp_path: Path):
    runner = FakeRunner([])
    supervisor = TaskSupervisor(
        FakeSession(),
        cwd=tmp_path,
        runner=runner,
        verify_command="python -m pytest",
    )

    result = asyncio.run(supervisor.run("explain", mode=TaskMode.ASK))

    assert result.status is TaskStatus.NO_CHANGES
    assert runner.calls == []


def test_supervisor_verifies_after_change_and_reports_result(tmp_path: Path):
    target = tmp_path / "app.py"

    def edit(_text):
        target.write_text("changed", encoding="utf-8")

    runner = FakeRunner(
        [VerificationResult(TaskStatus.VERIFIED, command="python -m pytest", exit_code=0)]
    )
    supervisor = TaskSupervisor(
        FakeSession(edit),
        cwd=tmp_path,
        runner=runner,
        verify_command="python -m pytest",
    )

    result = asyncio.run(supervisor.run("fix", mode=TaskMode.CODE))

    assert result.status is TaskStatus.VERIFIED
    assert result.changed_files == ("app.py",)
    assert runner.calls == ["python -m pytest"]


def test_supervisor_repairs_once_after_verification_failure(tmp_path: Path):
    target = tmp_path / "app.py"
    calls = 0

    def edit(_text):
        nonlocal calls
        calls += 1
        target.write_text(f"changed-{calls}", encoding="utf-8")

    runner = FakeRunner(
        [
            VerificationResult(
                TaskStatus.FAILED,
                command="pytest",
                exit_code=1,
                output_tail="assertion failed",
            ),
            VerificationResult(TaskStatus.VERIFIED, command="pytest", exit_code=0),
        ]
    )
    supervisor = TaskSupervisor(
        FakeSession(edit), cwd=tmp_path, runner=runner, verify_command="pytest"
    )

    result = asyncio.run(supervisor.run("fix", mode=TaskMode.CODE))

    assert result.status is TaskStatus.VERIFIED
    assert result.repair_attempts == 1
    assert len(runner.calls) == 2


def test_supervisor_stops_on_repeated_failure_fingerprint(tmp_path: Path):
    target = tmp_path / "app.py"

    def edit(_text):
        target.write_text("same", encoding="utf-8")

    failure = VerificationResult(
        TaskStatus.FAILED, command="pytest", exit_code=1, output_tail="same failure"
    )
    runner = FakeRunner([failure, failure, failure])
    supervisor = TaskSupervisor(
        FakeSession(edit), cwd=tmp_path, runner=runner, verify_command="pytest", max_repairs=3
    )

    result = asyncio.run(supervisor.run("fix", mode=TaskMode.CODE))

    assert result.status is TaskStatus.FAILED
    assert result.repair_attempts == 1
    assert len(runner.calls) == 2


def test_supervisor_reports_unverified_without_command(tmp_path: Path):
    target = tmp_path / "app.txt"
    supervisor = TaskSupervisor(
        FakeSession(lambda _text: target.write_text("changed", encoding="utf-8")),
        cwd=tmp_path,
        runner=FakeRunner([]),
    )

    result = asyncio.run(supervisor.run("edit", mode=TaskMode.CODE))

    assert result.status is TaskStatus.UNVERIFIED


def test_supervisor_cancel_stops_active_agent_task(tmp_path: Path):
    gate = asyncio.Event()

    class SlowSession(FakeSession):
        async def run(self, text, *, policy=None):
            await gate.wait()

    async def scenario():
        supervisor = TaskSupervisor(SlowSession(), cwd=tmp_path)
        task = asyncio.create_task(supervisor.run("wait", mode=TaskMode.CODE))
        await asyncio.sleep(0)
        supervisor.cancel()
        return await task

    result = asyncio.run(scenario())
    assert result.status is TaskStatus.CANCELLED
