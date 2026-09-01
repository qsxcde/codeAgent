"""V5-04 Subagent timeout, budget and bounded-cleanup regressions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message
from codeagent.core.contracts.ports import PolicyDecision
from codeagent.core.contracts.subagents import (
    SubagentBudget,
    SubagentReasonCode,
    SubagentRequest,
    SubagentStatus,
)


def _request(delegation_id: str, budget: SubagentBudget) -> SubagentRequest:
    return SubagentRequest(
        delegation_id=delegation_id,
        parent_run_id="parent-run",
        task="inspect repository",
        budget=budget,
    )


@dataclass
class _EventChild:
    session_id: str
    events: tuple[AgentEvent, ...] = ()
    block: asyncio.Event | None = None
    close_error: Exception | None = None
    uncooperative_cancel: bool = False
    callbacks: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.active_run_id: str | None = None
        self.last_outcome: Any = None
        self.history: list[Message] = [Message(role="assistant", content="done")]
        self.started = asyncio.Event()
        self.closed = False
        self.aborted = False
        self._task: asyncio.Task[Any] | None = None

    async def run(self, prompt: str) -> None:
        del prompt
        self._task = asyncio.current_task()
        run_id = f"run-{self.session_id}"
        self.active_run_id = run_id
        self.started.set()
        try:
            for event in self.events:
                for callback in tuple(self.callbacks):
                    callback(event)
            if self.block is not None:
                await self.block.wait()
        finally:
            self.active_run_id = None
            self.last_outcome = type("Outcome", (), {"run_id": run_id})()

    def subscribe(self, callback):
        self.callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self.callbacks:
                self.callbacks.remove(callback)

        return unsubscribe

    def abort(self) -> bool:
        self.aborted = True
        if self.uncooperative_cancel:
            return False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            return True
        return False

    async def cancel_and_wait(self, timeout: float | None = None) -> bool:
        del timeout
        if self.uncooperative_cancel:
            await asyncio.sleep(10)
        self.abort()
        return True

    async def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


@pytest.mark.integration
async def test_runner_applies_tool_call_budget_and_preserves_reason() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild(
        "budget",
        events=tuple(
            AgentEvent(
                EventType.TOOL_QUEUED,
                metadata={"tool_call_id": f"call-{index}"},
            )
            for index in range(3)
        ),
    )
    runner = SerialSubagentRunner(lambda request: child)

    result = await runner.execute(
        _request("delegation-budget", SubagentBudget(max_tool_calls=2, timeout_seconds=1))
    )

    assert result.status is SubagentStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.BUDGET_EXCEEDED.value
    assert child.aborted is True
    assert child.closed is True


@pytest.mark.integration
async def test_runner_applies_turn_budget_and_preserves_reason() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild(
        "turn-budget",
        events=(
            AgentEvent(EventType.TURN_START),
            AgentEvent(EventType.TURN_START),
        ),
    )
    runner = SerialSubagentRunner(lambda request: child)

    result = await runner.execute(
        _request("delegation-turn-budget", SubagentBudget(max_turns=1, timeout_seconds=1))
    )

    assert result.status is SubagentStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.BUDGET_EXCEEDED.value
    assert child.closed is True


@pytest.mark.integration
async def test_runner_timeout_covers_active_child_and_returns_timeout() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild("timeout", block=asyncio.Event())
    runner = SerialSubagentRunner(lambda request: child, cleanup_timeout=0.05)

    result = await runner.execute(
        _request("delegation-timeout", SubagentBudget(timeout_seconds=0.01))
    )

    assert result.status is SubagentStatus.TIMED_OUT
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.TIMEOUT.value
    assert child.aborted is True
    assert child.closed is True


@pytest.mark.integration
async def test_runner_timeout_covers_serial_queue_wait() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    release = asyncio.Event()
    created = asyncio.Event()
    children: list[_EventChild] = []

    def factory(request):
        child = _EventChild(request.delegation_id, block=None if children else release)
        children.append(child)
        created.set()
        return child

    runner = SerialSubagentRunner(factory, cleanup_timeout=0.05)
    first_task = asyncio.create_task(
        runner.execute(_request("delegation-first", SubagentBudget(timeout_seconds=1)))
    )
    await asyncio.wait_for(created.wait(), timeout=1)
    await asyncio.wait_for(children[0].started.wait(), timeout=1)

    second = await runner.execute(
        _request("delegation-second", SubagentBudget(timeout_seconds=0.01))
    )

    assert second.status is SubagentStatus.TIMED_OUT
    assert len(children) == 1
    release.set()
    first = await first_task
    assert first.status is SubagentStatus.COMPLETED


@pytest.mark.integration
async def test_runner_marks_cleanup_uncertain_after_close_failure() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild("close-failure", close_error=RuntimeError("close failed"))
    runner = SerialSubagentRunner(lambda request: child, cleanup_timeout=0.05)

    result = await runner.execute(
        _request("delegation-close-failure", SubagentBudget(timeout_seconds=1))
    )

    assert result.status is SubagentStatus.COMPLETED
    assert result.cleanup_uncertain is True
    assert any("关闭子 Session" in item for item in result.diagnostics)


@pytest.mark.integration
async def test_runner_bounds_uncooperative_cleanup_after_timeout() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _EventChild(
        "uncooperative",
        block=asyncio.Event(),
        uncooperative_cancel=True,
    )
    runner = SerialSubagentRunner(lambda request: child, cleanup_timeout=0.01)

    result = await runner.execute(
        _request("delegation-uncooperative", SubagentBudget(timeout_seconds=0.01))
    )

    assert result.status is SubagentStatus.TIMED_OUT
    assert result.cleanup_uncertain is True
    assert result.failure is not None
    assert result.failure.cleanup_uncertain is True


@pytest.mark.integration
async def test_fake_client_child_turn_budget_returns_failure_and_parent_continues() -> None:
    """真实组合根应把 max_turns 映射到子 Session，并让父循环继续。"""
    from unittest.mock import patch

    root_client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "delegate",
                        "args": {
                            "task": "inspect one file",
                            "budget": {"max_turns": 1},
                        },
                        "id": "budget-delegate-call",
                    }
                ]
            },
            {"content": "父 Agent 已处理预算结果"},
        ]
    )
    child_client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "read",
                        "args": {"file_path": "README.md"},
                        "id": "child-read-call",
                    }
                ]
            }
        ]
    )

    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        side_effect=[root_client, child_client],
    ):
        from codeagent.app.container import create_agent_session

        session = create_agent_session(provider="fake", store=None)
        seen: list[AgentEvent] = []
        session.subscribe(seen.append)
        await session.run("开始预算测试")
        await session.close()

    delegate_results = [
        event
        for event in seen
        if event.type == EventType.TOOL_RESULT
        and event.metadata.get("tool_name") == "delegate"
    ]
    assert len(delegate_results) == 1
    assert "max_turns" in delegate_results[0].payload
    assert session.history[-1].content == "父 Agent 已处理预算结果"
    assert child_client.call_history


@pytest.mark.integration
async def test_fake_client_confirmation_wait_is_woken_by_subagent_timeout() -> None:
    """子 Session 等待确认时，runner 超时应取消确认并完成关闭。"""
    from codeagent.app.composition.tools.adapter import adapt_tools
    from codeagent.app.container import ChatModelPort
    from codeagent.core.orchestration.config import AgentLoopConfig
    from codeagent.session import AgentSession, EventBus
    from codeagent.tools.atomic import BashTool
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    class AskPolicy:
        def decide(self, tool_name: str, args: dict) -> PolicyDecision:
            del args
            return PolicyDecision("ask", f"confirm:{tool_name}")

    child = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(
                    steps=[
                        {
                            "tool_calls": [
                                {
                                    "name": "bash",
                                    "args": {"command": "echo child"},
                                    "id": "child-bash-call",
                                }
                            ]
                        }
                    ]
                )
            ),
            tools=adapt_tools([BashTool()]),
        ),
        EventBus(),
        policy=AskPolicy(),
    )
    runner = SerialSubagentRunner(lambda request: child, cleanup_timeout=0.05)

    result = await runner.execute(
        _request(
            "delegation-confirmation-timeout",
            SubagentBudget(timeout_seconds=0.03),
        )
    )

    assert result.status is SubagentStatus.TIMED_OUT
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.TIMEOUT.value
    assert child._runtime.confirmation.active_request_ids == ()
    assert child.is_running is False
    assert child._closed is True
