"""V5-07 headless Subagent 状态行回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codeagent.app import headless
from codeagent.core.contracts.events import AgentEvent, EventType


def _event(
    event_type: str,
    delegation_id: str = "delegation-1",
    *,
    status: str = "running",
    child_run_id: str | None = "child-run",
    child_phase: str | None = None,
    elapsed_ms: int | None = None,
    payload: object = None,
) -> AgentEvent:
    return AgentEvent(
        event_type,
        payload=payload,
        metadata={
            "delegation_id": delegation_id,
            "parent_run_id": "parent-run",
            "child_run_id": child_run_id,
            "subagent_status": status,
            "child_phase": child_phase,
            "elapsed_ms": elapsed_ms,
        },
    )


@pytest.mark.unit
def test_headless_projector_emits_stable_bounded_lines_and_deduplicates_terminal() -> None:
    from codeagent.app.subagent_observability import SubagentLineProjector

    projector = SubagentLineProjector()
    events = [
        _event(EventType.SUBAGENT_QUEUED, status="queued", child_run_id=None),
        _event(EventType.SUBAGENT_QUEUED, status="queued", child_run_id=None),
        _event(EventType.SUBAGENT_STARTED, status="running", child_phase="starting"),
        _event(
            EventType.SUBAGENT_PROGRESS,
            status="waiting_confirmation",
            child_phase="awaiting_confirmation",
            elapsed_ms=1_250,
            payload={"tool_name": "read", "reason": "完整确认 prompt 不应出现在 CLI" * 100},
        ),
        _event(
            EventType.SUBAGENT_FINISHED,
            status="failed",
            payload={
                "summary": "有限结论" * 100,
                "failure": {"reason_code": "timeout", "message": "内部错误" * 100},
                "cleanup_uncertain": True,
            },
        ),
        _event(
            EventType.SUBAGENT_FINISHED,
            status="failed",
            payload={"failure": {"reason_code": "timeout"}},
        ),
        _event(
            EventType.SUBAGENT_PROGRESS,
            status="running",
            child_phase="tool_running",
            elapsed_ms=9_999,
        ),
    ]

    lines = [line for event in events if (line := projector.project(event))]

    assert len(lines) == 4
    assert all(line.startswith("子Agent状态: ") for line in lines)
    assert any("status=waiting_confirmation" in line for line in lines)
    assert any("status=failed" in line and "reason=timeout" in line for line in lines)
    assert any("cleanup_uncertain=true" in line for line in lines)
    assert all(len(line) <= 240 for line in lines)
    assert all("完整确认 prompt" not in line for line in lines)
    assert all("内部错误" * 20 not in line for line in lines)


class _FakeSession:
    def __init__(self, events: list[AgentEvent]) -> None:
        self.events = events
        self._subscriber = None

    def subscribe(self, callback):
        self._subscriber = callback
        return lambda: None

    def emit(self, event: AgentEvent) -> None:
        assert self._subscriber is not None
        self._subscriber(event)


@pytest.mark.unit
async def test_headless_once_prints_child_lines_near_parent_reply(monkeypatch, capsys) -> None:
    session = _FakeSession([])

    class FakeSupervisor:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run(self, _prompt, *, mode):
            del mode
            session.emit(_event(EventType.SUBAGENT_QUEUED, status="queued", child_run_id=None))
            session.emit(_event(EventType.SUBAGENT_STARTED, status="running", child_phase="starting"))
            session.emit(AgentEvent(EventType.AGENT_MESSAGE, payload="父回复"))
            session.emit(
                _event(
                    EventType.SUBAGENT_FINISHED,
                    status="completed",
                    payload={"summary": "有限结论"},
                )
            )
            return SimpleNamespace(status=SimpleNamespace(value="no_changes"), message="")

    monkeypatch.setattr(headless, "TaskSupervisor", FakeSupervisor)

    await headless._headless_once(session, "父请求")
    output = capsys.readouterr().out

    assert "你: 父请求" in output
    assert "父回复" in output
    assert "子Agent状态: id=delegation-1 status=queued" in output
    assert "子Agent状态: id=delegation-1 status=completed" in output
    assert "有限结论" in output
    assert output.count("status=completed") == 1
    assert "child-run" not in output


@pytest.mark.unit
async def test_headless_loop_scopes_child_lines_to_each_input(monkeypatch, capsys) -> None:
    session = _FakeSession([])
    run_count = 0

    class FakeSupervisor:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run(self, _prompt, *, mode):
            nonlocal run_count
            del mode
            run_count += 1
            delegation_id = f"delegation-{run_count}"
            session.emit(
                _event(EventType.SUBAGENT_QUEUED, delegation_id, status="queued", child_run_id=None)
            )
            session.emit(AgentEvent(EventType.AGENT_MESSAGE, payload=f"回复-{run_count}"))
            session.emit(
                _event(
                    EventType.SUBAGENT_FINISHED,
                    delegation_id,
                    status="cancelled",
                    payload={"failure": {"reason_code": "parent_cancelled"}},
                )
            )
            return SimpleNamespace(status=SimpleNamespace(value="no_changes"), message="")

    monkeypatch.setattr(headless, "TaskSupervisor", FakeSupervisor)
    monkeypatch.setattr(headless.sys, "stdin", iter(["第一轮\n", "第二轮\n"]))

    await headless._headless_loop(session)
    output = capsys.readouterr().out

    assert output.count("id=delegation-1 status=") == 2
    assert output.count("id=delegation-2 status=") == 2
    assert "reason=parent_cancelled" in output
    assert "回复-1" in output and "回复-2" in output
