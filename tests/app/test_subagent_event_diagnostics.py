"""V5-06 Subagent event envelope, lifecycle and cleanup regressions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from codeagent.app.tui.state.model import TuiModel
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message
from codeagent.core.contracts.subagents import (
    SubagentBudget,
    SubagentReasonCode,
    SubagentRequest,
    SubagentStatus,
)


def _request(delegation_id: str, *, budget: SubagentBudget | None = None) -> SubagentRequest:
    return SubagentRequest(
        delegation_id=delegation_id,
        parent_run_id="parent-run",
        task="inspect the repository",
        budget=budget or SubagentBudget(),
    )


class _EventChild:
    """Small child-session double that exposes real callback races."""

    def __init__(
        self,
        session_id: str,
        *,
        block: asyncio.Event | None = None,
        cleanup_confirmed: bool = True,
        turn_events: int = 1,
    ) -> None:
        self.session_id = session_id
        self.block = block
        self.cleanup_confirmed = cleanup_confirmed
        self.turn_events = turn_events
        self.active_run_id: str | None = None
        self.last_outcome: Any = None
        self.history: list[Message] = []
        self.started = asyncio.Event()
        self.closed = False
        self.aborted = False
        self._task: asyncio.Task[Any] | None = None
        self._callbacks: list[Any] = []
        self.last_callback: Any = None
        self._sequence = 0

    async def run(self, task: str) -> None:
        del task
        self._task = asyncio.current_task()
        self.active_run_id = f"child-run-{self.session_id}"
        run_id = self.active_run_id
        self.started.set()
        outcome = "completed"
        try:
            for _ in range(self.turn_events):
                self._emit(EventType.TURN_START)
            self._emit(EventType.SESSION_STARTED, phase="starting")
            self._emit(EventType.MESSAGE_START, phase="model_wait")
            self._emit(EventType.TOOL_STARTED, phase="tool_running", tool_name="read")
            self._emit(
                EventType.CONFIRMATION_REQUESTED,
                phase="awaiting_confirmation",
                payload={"reason": "r" * 2_000, "tool": "read"},
            )
            self._emit(EventType.TOOL_FINISHED, phase="tool_running", tool_name="read")
            if self.block is not None:
                await self.block.wait()
            self.history = [Message(role="assistant", content="child conclusion")]
            self._emit(EventType.MESSAGE_END, phase="model_wait")
        except asyncio.CancelledError:
            outcome = "cancelled"
            self._emit(EventType.ABORTED, phase="cancelling")
            raise
        finally:
            self.active_run_id = None
            self.last_outcome = SimpleNamespace(phase=outcome, run_id=run_id)

    def _emit(
        self,
        event_type: str,
        *,
        phase: str | None = None,
        tool_name: str | None = None,
        payload: Any = None,
    ) -> None:
        self._sequence += 1
        event = AgentEvent(
            event_type,
            payload=payload,
            session_id=self.session_id,
            run_id=self.active_run_id,
            metadata={"sequence": self._sequence, "phase": phase} if phase else {"sequence": self._sequence},
            phase=phase,
            tool_name=tool_name,
        )
        for callback in tuple(self._callbacks):
            callback(event)

    def subscribe(self, callback: Any):
        self._callbacks.append(callback)
        self.last_callback = callback

        def unsubscribe() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    def abort(self) -> bool:
        self.aborted = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            return True
        return False

    async def cancel_and_wait(self, timeout: float | None = None) -> bool:
        del timeout
        self.abort()
        return self.cleanup_confirmed

    async def close(self) -> None:
        self.closed = True


@pytest.mark.unit
async def test_runner_emits_bounded_correlated_envelopes_and_one_terminal_event() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild("bounded")
    events: list[AgentEvent] = []
    result = await SerialSubagentRunner(lambda _request: child).execute(
        _request("delegation-bounded"), on_event=events.append
    )

    assert result.status is SubagentStatus.COMPLETED
    assert [event.type for event in events[:2]] == [
        EventType.SUBAGENT_QUEUED,
        EventType.SUBAGENT_STARTED,
    ]
    finished = [event for event in events if event.type == EventType.SUBAGENT_FINISHED]
    progress = [event for event in events if event.type == EventType.SUBAGENT_PROGRESS]
    assert len(finished) == 1
    assert progress
    assert all(event.parent_run_id == "parent-run" for event in events)
    assert all(event.delegation_id == "delegation-bounded" for event in events)
    assert all(event.type != EventType.TOOL_EXECUTION_UPDATE for event in events)
    assert all(isinstance(event.payload, dict) for event in progress)
    assert all("r" * 2_000 not in str(event.payload) for event in progress)
    assert [event.child_sequence for event in progress] == sorted(
        event.child_sequence for event in progress
    )
    assert finished[0].run_id == result.child_run_id
    assert finished[0].payload["summary"] == "child conclusion"
    assert finished[0].payload["delegation_id"] == result.delegation_id
    assert child.closed is True


@pytest.mark.unit
async def test_runner_isolates_async_observer_failure_and_ignores_late_child_event() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild("late")
    observed: list[str] = []
    runner = SerialSubagentRunner(lambda _request: child)

    async def observer(event: AgentEvent) -> None:
        observed.append(event.type)
        if event.type == EventType.SUBAGENT_PROGRESS:
            raise RuntimeError("observer failed")

    events: list[AgentEvent] = []
    async def on_event(event: AgentEvent) -> None:
        events.append(event)
        await observer(event)

    result = await runner.execute(_request("delegation-late"), on_event=on_event)

    assert result.status is SubagentStatus.COMPLETED
    assert any("子事件回调" in item for item in result.diagnostics)
    before = len(events)
    child.last_callback(
        AgentEvent(
            EventType.MESSAGE_UPDATE,
            payload="late child transcript" * 100,
            session_id=child.session_id,
            run_id=result.child_run_id,
            metadata={"sequence": 10_000},
        )
    )
    assert len(events) == before
    assert runner.active_delegations == {}
    assert EventType.SUBAGENT_FINISHED in observed


@pytest.mark.unit
async def test_runner_emits_one_cancelled_terminal_with_cleanup_diagnostic() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild("cancel", block=asyncio.Event(), cleanup_confirmed=False)
    events: list[AgentEvent] = []
    runner = SerialSubagentRunner(lambda _request: child)
    task = asyncio.create_task(runner.execute(_request("delegation-cancel"), on_event=events.append))
    await asyncio.wait_for(child.started.wait(), timeout=1)

    assert await runner.cancel("delegation-cancel") is True
    result = await task

    finished = [event for event in events if event.type == EventType.SUBAGENT_FINISHED]
    assert result.status is SubagentStatus.CANCELLED
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.PARENT_CANCELLED.value
    assert result.cleanup_uncertain is True
    assert len(finished) == 1
    assert finished[0].subagent_status == SubagentStatus.CANCELLED.value
    assert finished[0].cleanup_uncertain is True
    assert child.aborted is True


@pytest.mark.unit
async def test_runner_maps_startup_failure_to_one_terminal_event() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    events: list[AgentEvent] = []

    def factory(_request: SubagentRequest):
        raise RuntimeError("cannot create child")

    result = await SerialSubagentRunner(factory).execute(
        _request("delegation-startup"), on_event=events.append
    )

    finished = [event for event in events if event.type == EventType.SUBAGENT_FINISHED]
    assert result.status is SubagentStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.STARTUP_FAILED.value
    assert len(finished) == 1
    assert finished[0].payload["failure"]["phase"] == "starting"


@pytest.mark.unit
async def test_runner_preserves_budget_exceeded_as_failed_terminal() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild("budget", block=asyncio.Event(), turn_events=2)
    events: list[AgentEvent] = []
    result = await SerialSubagentRunner(lambda _request: child).execute(
        _request(
            "delegation-budget",
            budget=SubagentBudget(max_turns=1),
        ),
        on_event=events.append,
    )

    finished = [event for event in events if event.type == EventType.SUBAGENT_FINISHED]
    assert result.status is SubagentStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.BUDGET_EXCEEDED.value
    assert len(finished) == 1
    assert finished[0].payload["failure"]["reason_code"] == "budget_exceeded"


@pytest.mark.integration
async def test_real_fake_parent_receives_top_level_subagent_events_and_continues() -> None:
    from codeagent.ai.providers.fake import FakeClient

    root_client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {
                        "id": "delegate-call",
                        "name": "delegate",
                        "args": {"task": "inspect child context", "profile": "explore"},
                    }
                ]
            },
            {"content": "父 Agent 已综合子结论"},
        ]
    )
    child_client = FakeClient(response="子 Agent 的内部输出")

    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        side_effect=[root_client, child_client],
    ):
        from codeagent.app.container import create_agent_session

        session = create_agent_session(provider="fake", store=None)
        events: list[AgentEvent] = []
        session.subscribe(events.append)
        await session.run("父级请求")
        await session.close()

    subagent_events = [
        event for event in events if event.type in {
            EventType.SUBAGENT_QUEUED,
            EventType.SUBAGENT_STARTED,
            EventType.SUBAGENT_PROGRESS,
            EventType.SUBAGENT_FINISHED,
        }
    ]
    finished = [event for event in subagent_events if event.type == EventType.SUBAGENT_FINISHED]
    assert [event.type for event in subagent_events[:2]] == [
        EventType.SUBAGENT_QUEUED,
        EventType.SUBAGENT_STARTED,
    ]
    assert finished and len(finished) == 1
    assert finished[0].run_id == finished[0].child_run_id
    assert finished[0].parent_run_id
    assert finished[0].parent_sequence is not None
    assert all(
        not (event.type == EventType.TOOL_PROGRESS and isinstance(event.payload, AgentEvent))
        for event in events
    )
    assert any(message.content == "父 Agent 已综合子结论" for message in session.history)
    assert all(
        "子 Agent 的内部输出" not in str(event.payload)
        for event in subagent_events
        if event.type == EventType.SUBAGENT_PROGRESS
    )


@pytest.mark.unit
def test_tui_model_ignores_unregistered_child_subagent_events() -> None:
    model = TuiModel(clock=lambda: 1.0)
    model.apply(
        AgentEvent(
            EventType.SESSION_STARTED,
            payload="parent prompt",
            session_id="parent-session",
            run_id="parent-run",
        )
    )
    before = model.runtime

    model.apply(
        AgentEvent(
            EventType.SUBAGENT_PROGRESS,
            payload={"child_event_type": EventType.TEXT_DELTA},
            session_id="child-session",
            run_id="child-run",
            parent_run_id="parent-run",
            child_run_id="child-run",
            delegation_id="delegation-1",
        )
    )

    assert model.runtime == before
    assert model.transcript.block_count == 1
    assert model.subagent_blocks == []
