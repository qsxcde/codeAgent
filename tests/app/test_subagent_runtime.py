"""V5-02 Subagent runtime tests: request mapping, isolation and cleanup."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.core.contracts.messages import Message, ToolResult
from codeagent.core.contracts.subagents import (
    SubagentArtifact,
    SubagentEvidence,
    SubagentFailure,
    SubagentFinding,
    SubagentReasonCode,
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
    SubagentUsage,
)
from codeagent.core.contracts.events import AgentEvent


def _request(delegation_id: str, task: str = "inspect the repository") -> SubagentRequest:
    return SubagentRequest(
        delegation_id=delegation_id,
        parent_run_id="parent-run",
        task=task,
    )


class _RecordingRunner:
    def __init__(self, result: SubagentResult) -> None:
        self.result = result
        self.requests: list[SubagentRequest] = []

    async def execute(self, request: SubagentRequest, *, on_event=None) -> SubagentResult:
        self.requests.append(request)
        return self.result

    async def cancel(self, delegation_id: str) -> bool:
        return False


class _RaisingRunner(_RecordingRunner):
    async def execute(self, request: SubagentRequest, *, on_event=None) -> SubagentResult:
        del request, on_event
        raise RuntimeError("runner unavailable")


@pytest.mark.parametrize(
    ("status", "error", "reason"),
    [
        (SubagentStatus.COMPLETED, False, None),
        (SubagentStatus.FAILED, True, SubagentReasonCode.EXECUTION_FAILED),
    ],
)
async def test_delegate_tool_maps_subagent_result_to_tool_result(status, error, reason):
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    failure = (
        SubagentFailure(
            reason_code=SubagentReasonCode.EXECUTION_FAILED,
            message="child failed",
            phase="running",
        )
        if reason is not None
        else None
    )
    runner = _RecordingRunner(
        SubagentResult(
            delegation_id="delegation-1",
            status=status,
            child_run_id="child-run-1",
            attempt_id="attempt-1",
            summary="child summary",
            failure=failure,
        )
    )
    tool = DelegateTool(runner).bind_parent_run_id("parent-run-1")

    result = await tool.execute(
        "call-1",
        {"task": "inspect files", "profile": "read_only"},
    )

    assert isinstance(result, ToolResult)
    assert result.error is error
    assert result.name == "delegate"
    assert result.details["delegation_id"] == "delegation-1"
    assert result.details["child_run_id"] == "child-run-1"
    assert result.details["subagent_status"] == status.value
    if reason is not None:
        assert result.details["reason_code"] == reason.value
    assert len(runner.requests) == 1
    request = runner.requests[0]
    assert request.parent_run_id == "parent-run-1"
    assert request.task == "inspect files"
    assert request.profile == "read_only"
    assert request.depth == 1
    assert request.max_depth == 1


async def test_delegate_tool_exposes_structured_result_details_as_json_safe_values():
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    evidence = SubagentEvidence(
        evidence_id="evidence-1",
        source="tool:read",
        summary="observed fact",
        locator="src/app.py:1-2",
        excerpt="value = 1",
        completeness="complete",
    )
    result = SubagentResult(
        delegation_id="delegation-1",
        status=SubagentStatus.COMPLETED,
        child_run_id="child-run-1",
        summary="child summary",
        findings=(SubagentFinding("finding", ("evidence-1",)),),
        evidence=(evidence,),
        usage=SubagentUsage(input_tokens=10, output_tokens=2),
        artifact=SubagentArtifact(ref="artifact-1", kind="tool_output", label="report"),
    )

    mapped = await DelegateTool(_RecordingRunner(result)).bind_parent_run_id(
        "parent-run-1"
    ).execute("call-1", {"task": "inspect files"})

    assert mapped.details["summary"] == "child summary"
    assert mapped.details["findings"] == [
        {"summary": "finding", "evidence_ids": ["evidence-1"]}
    ]
    assert mapped.details["evidence"] == [evidence.to_dict()]
    assert mapped.details["usage"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
    }
    assert mapped.details["artifact"] == {
        "ref": "artifact-1",
        "kind": "tool_output",
        "label": "report",
    }
    json.dumps(mapped.details, ensure_ascii=False)


async def test_delegate_tool_keeps_empty_structured_details_for_legacy_result():
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    result = await DelegateTool(
        _RecordingRunner(
            SubagentResult(
                delegation_id="delegation-1",
                status=SubagentStatus.COMPLETED,
                summary="legacy",
            )
        )
    ).bind_parent_run_id("parent-run-1").execute("call-1", {"task": "inspect"})

    assert result.details["findings"] == []
    assert result.details["evidence"] == []
    assert result.details["usage"] is None
    assert result.details["artifact"] is None


async def test_delegate_tool_rejects_invalid_arguments_without_starting_child():
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    runner = _RecordingRunner(
        SubagentResult(
            delegation_id="unused",
            status=SubagentStatus.COMPLETED,
            summary="unused",
        )
    )
    tool = DelegateTool(runner).bind_parent_run_id("parent-run")

    empty = await tool.execute("call-1", {"task": "   "})
    write_profile = await tool.execute(
        "call-2", {"task": "write files", "profile": "write"}
    )
    unbound = await DelegateTool(runner).execute("call-3", {"task": "inspect"})

    assert empty.error and empty.details["reason_code"] == "invalid_request"
    assert write_profile.error and write_profile.details["reason_code"] == "permission_denied"
    assert unbound.error and unbound.details["reason_code"] == "invalid_request"
    assert runner.requests == []


async def test_delegate_tool_normalizes_unexpected_runner_failure():
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    result = await DelegateTool(_RaisingRunner(SubagentResult(
        delegation_id="unused", status=SubagentStatus.COMPLETED, summary="unused"
    ))).bind_parent_run_id("parent-run").execute(
        "call-1", {"task": "inspect"}
    )

    assert result.error is True
    assert result.status == "failed"
    assert result.details["reason_code"] == SubagentReasonCode.EXECUTION_FAILED.value


@dataclass
class _FakeChildSession:
    session_id: str
    answer: str
    block: asyncio.Event | None = None
    fail: Exception | None = None

    def __post_init__(self) -> None:
        self.active_run_id: str | None = None
        self.last_outcome: Any = None
        self.history: list[Message] = []
        self.started = asyncio.Event()
        self.closed = False
        self.aborted = False
        self._task: asyncio.Task[Any] | None = None
        self.max_active = 0
        self.active_count = 0

    async def run(self, task: str) -> None:
        del task
        self._task = asyncio.current_task()
        self.active_run_id = f"run-{self.session_id}"
        run_id = self.active_run_id
        self.active_count += 1
        self.max_active = max(self.max_active, self.active_count)
        self.started.set()
        try:
            if self.block is not None:
                await self.block.wait()
            if self.fail is not None:
                raise self.fail
            self.history = [Message(role="assistant", content=self.answer)]
        finally:
            self.active_count -= 1
            self.active_run_id = None
            self.last_outcome = type("Outcome", (), {"run_id": run_id})()

    def abort(self) -> bool:
        self.aborted = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            return True
        return False

    async def cancel_and_wait(self, timeout: float | None = None) -> bool:
        del timeout
        self.abort()
        return True

    async def close(self) -> None:
        self.closed = True

    def subscribe(self, callback):
        del callback
        return lambda: None


async def test_serial_runner_queues_second_child_and_closes_each_session():
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    release = asyncio.Event()
    children: list[_FakeChildSession] = []

    def factory(request: SubagentRequest):
        child = _FakeChildSession(request.delegation_id, request.task, release if not children else None)
        children.append(child)
        return child

    runner = SerialSubagentRunner(factory)
    first_task = asyncio.create_task(runner.execute(_request("delegation-1", "first")))
    await asyncio.sleep(0)
    await asyncio.wait_for(children[0].started.wait(), timeout=1)
    second_task = asyncio.create_task(runner.execute(_request("delegation-2", "second")))
    await asyncio.sleep(0)

    assert len(children) == 1
    assert not second_task.done()
    release.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert [first.status, second.status] == [SubagentStatus.COMPLETED] * 2
    assert [first.child_run_id, second.child_run_id] == ["run-delegation-1", "run-delegation-2"]
    assert all(child.closed for child in children)
    assert all(child.max_active == 1 for child in children)
    assert runner.active_delegations == {}


async def test_serial_runner_normalizes_failure_and_cleans_child():
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _FakeChildSession("failed", "unused", fail=RuntimeError("boom"))
    runner = SerialSubagentRunner(lambda request: child)

    result = await runner.execute(_request("delegation-failed"))

    assert result.status is SubagentStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.EXECUTION_FAILED.value
    assert result.child_run_id == "run-failed"
    assert child.closed is True
    assert runner.active_delegations == {}


async def test_serial_runner_cancel_targets_only_active_child():
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    child = _FakeChildSession("cancelled", "unused", block=asyncio.Event())
    runner = SerialSubagentRunner(lambda request: child)
    task = asyncio.create_task(runner.execute(_request("delegation-cancel")))
    await asyncio.wait_for(child.started.wait(), timeout=1)

    assert await runner.cancel("delegation-cancel") is True
    result = await task

    assert result.status is SubagentStatus.CANCELLED
    assert result.failure is not None
    assert result.failure.reason_code == SubagentReasonCode.PARENT_CANCELLED.value
    assert child.aborted is True
    assert child.closed is True
    assert await runner.cancel("unknown") is False


async def test_real_parent_delegate_runs_isolated_child_and_returns_only_result():
    root_client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "delegate",
                        "args": {"task": "inspect child-only context", "profile": "read_only"},
                        "id": "delegate-call",
                    }
                ]
            },
            {"content": "父 Agent 已综合子结论"},
        ]
    )
    child_client = FakeClient(response="子 Agent 的只读结论")

    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        side_effect=[root_client, child_client],
    ):
        from codeagent.app.container import create_agent_session

        session = create_agent_session(provider="fake", store=None)
        await session.run("父上下文秘密：不要复制到子运行")
        await session.close()

    assert "delegate" in root_client.call_history[0]["bound_tools"]
    assert "delegate" not in child_client.call_history[0]["bound_tools"]
    assert set(child_client.call_history[0]["bound_tools"]) <= {
        "read",
        "grep",
        "find",
        "ls",
        "skill",
    }
    child_contents = "\n".join(
        item["content"] for item in child_client.call_history[0]["messages"]
    )
    assert "inspect child-only context" in child_contents
    assert all("父上下文秘密" not in content for content in child_contents)
    assert any(item.content == "子 Agent 的只读结论" for item in session.history)
    assert any(item.content == "父 Agent 已综合子结论" for item in session.history)
    assert [item.role for item in session.history].count("assistant") == 2


@pytest.mark.integration
async def test_persisted_parent_keeps_bounded_subagent_record_without_child_session(tmp_path):
    root_client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "delegate",
                        "args": {"task": "persist child result", "profile": "read_only"},
                        "id": "persist-delegate-call",
                    }
                ]
            },
            {"content": "父 Agent 已保存结果"},
        ]
    )
    child_client = FakeClient(response="可恢复的子结论")
    from codeagent.session.persistence import JsonFileStore

    store = JsonFileStore(tmp_path / "sessions")
    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        side_effect=[root_client, child_client],
    ):
        from codeagent.app.container import create_agent_session

        session = create_agent_session(provider="fake", store=store, session_id="parent")
        await session.run("父级请求")
        await session.close()

    records = store.load_subagent_records("parent")
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].summary == "可恢复的子结论"
    assert [ref.id for ref in store.list()] == ["parent"]


async def test_real_child_session_failure_is_not_reported_as_success():
    class FailingClient(FakeClient):
        def _generate(self, messages, **kwargs):
            del messages, kwargs
            raise RuntimeError("child model failed")

    root_client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "delegate",
                        "args": {"task": "trigger child failure"},
                        "id": "failure-delegate-call",
                    }
                ]
            },
            {"content": "父 Agent 处理了子失败"},
        ]
    )

    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        side_effect=[root_client, FailingClient()],
    ):
        from codeagent.app.container import create_agent_session

        session = create_agent_session(provider="fake", store=None)
        await session.run("start")
        await session.close()

    tool_messages = [item for item in session.history if item.role == "tool"]
    assert len(tool_messages) == 1
    assert "子 Agent failed" in tool_messages[0].content
    assert "父 Agent 处理了子失败" in session.history[-1].content


async def test_session_manager_root_exposes_delegate_and_keeps_child_temporary():
    root_client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {
                        "name": "delegate",
                        "args": {"task": "inspect manager child", "profile": "read_only"},
                        "id": "manager-delegate-call",
                    }
                ]
            },
            {"content": "manager parent result"},
        ]
    )
    child_client = FakeClient(response="manager child result")

    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        side_effect=[root_client, child_client],
    ):
        from codeagent.app.container import create_session_manager

        manager = create_session_manager(provider="fake", store=None)
        session = manager.create()
        await session.run("manager parent prompt")
        await manager.close()

    assert any(item.content == "manager child result" for item in session.history)
    assert any(item.content == "manager parent result" for item in session.history)
    assert manager.current is session
