"""Structured Subagent result extraction and parent mapping regressions."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.composition.model.port import ChatModelPort
from codeagent.app.composition.subagent.runner import SerialSubagentRunner
from codeagent.core import AgentLoopConfig
from codeagent.core.contracts.messages import (
    Message,
    ToolCall,
    ToolExecutionStatus,
    ToolOutputMetadata,
    ToolResult,
)
from codeagent.core.contracts.subagents import (
    SubagentBudget,
    SubagentRequest,
    SubagentUsage,
)
from codeagent.session import AgentSession, EventBus


@dataclass
class _Child:
    history: list[Message]
    run_usage: object | None = None


class _ArtifactTool:
    name = "read"
    description = "read a prepared report"
    parameters = {"type": "object", "properties": {"file_path": {"type": "string"}}}

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        del arguments, signal, on_update
        return ToolResult(
            tool_call_id,
            "observed fact\n" * 200,
            name=self.name,
            status=ToolExecutionStatus.COMPLETED,
            cleanup_confirmed=True,
            output_metadata=ToolOutputMetadata(
                completeness="complete",
                path="report.txt",
                artifact_ref="artifact-report-1",
                total_lines=200,
                shown_lines=200,
            ),
        )


@pytest.mark.unit
def test_extract_child_facts_keeps_bounded_tool_evidence_and_first_artifact() -> None:
    from codeagent.app.composition.subagent.result_extraction import extract_child_facts

    child = _Child(
        history=[
            Message(
                role="assistant",
                tool_calls=[ToolCall(id="read-1", name="read")],
            ),
            Message(
                role="tool",
                tool_call_id="read-1",
                content="[1-2/200 行]\n" + ("timeout = 120\n" * 200),
                tool_output=ToolOutputMetadata(
                    completeness="truncated",
                    path="config.toml",
                    range_start=0,
                    range_end=2,
                    artifact_ref="artifact-1",
                    continuation="offset=2",
                    total_lines=200,
                    shown_lines=2,
                ),
            ),
            Message(role="assistant", content="自然语言结论，不是机器 findings"),
            Message(
                role="tool",
                tool_call_id="without-metadata",
                content="这条消息没有结构化元数据，不应进入 evidence",
            ),
        ]
    )

    facts = extract_child_facts(child)

    assert facts.findings == ()
    assert len(facts.evidence) == 1
    evidence = facts.evidence[0]
    assert evidence.evidence_id == "evidence-1"
    assert evidence.source == "tool:read"
    assert evidence.locator == "config.toml:1-2"
    assert evidence.completeness == "truncated"
    assert evidence.continuation == "offset=2"
    assert evidence.excerpt is not None
    assert len(evidence.excerpt) <= 1_200
    assert facts.artifact is not None
    assert facts.artifact.ref == "artifact-1"
    assert facts.artifact.kind == "tool_output"


@pytest.mark.unit
def test_extract_child_facts_limits_evidence_without_copying_transcript() -> None:
    from codeagent.app.composition.subagent.result_extraction import extract_child_facts

    history: list[Message] = []
    for index in range(40):
        call_id = f"call-{index}"
        history.extend(
            [
                Message(
                    role="assistant",
                    tool_calls=[ToolCall(id=call_id, name="grep")],
                ),
                Message(
                    role="tool",
                    tool_call_id=call_id,
                    content=f"observation-{index}",
                    tool_output=ToolOutputMetadata(
                        completeness="complete",
                        total_lines=1,
                        shown_lines=1,
                    ),
                ),
            ]
        )
    history.append(Message(role="assistant", content="final answer"))

    facts = extract_child_facts(_Child(history))

    assert len(facts.evidence) == 32
    assert facts.evidence[0].summary == "observation-0"
    assert facts.evidence[-1].summary == "observation-31"
    assert all(not hasattr(item, "history") for item in facts.evidence)


@pytest.mark.unit
def test_child_usage_prefers_run_total_and_falls_back_to_legacy_views() -> None:
    from codeagent.app.composition.subagent.result_extraction import child_usage

    child = _Child([], run_usage=SubagentUsage(input_tokens=30, output_tokens=12))
    child.last_actual_usage = SubagentUsage(input_tokens=3, output_tokens=1)  # type: ignore[attr-defined]
    assert child_usage(child) == SubagentUsage(input_tokens=30, output_tokens=12)

    legacy_child = _Child([])
    legacy_child.last_actual_usage = SubagentUsage(input_tokens=3, output_tokens=1)  # type: ignore[attr-defined]
    assert child_usage(legacy_child) == SubagentUsage(input_tokens=3, output_tokens=1)


@pytest.mark.unit
def test_runner_result_contains_extracted_child_facts() -> None:
    from codeagent.app.composition.subagent.active import ActiveDelegation
    from codeagent.app.composition.subagent.budget import effective_budget
    from codeagent.app.composition.subagent.runner_execution import _result_from_child
    from codeagent.core.contracts.subagents import SubagentStatus

    child = _Child(
        history=[
            Message(
                role="assistant",
                tool_calls=[ToolCall(id="call-1", name="read")],
            ),
            Message(
                role="tool",
                tool_call_id="call-1",
                content="observed fact",
                tool_output=ToolOutputMetadata(
                    completeness="complete",
                    path="src/app.py",
                    artifact_path="/tmp/report.txt",
                ),
            ),
        ],
        run_usage=SubagentUsage(input_tokens=8, output_tokens=2),
    )
    child.last_outcome = type("Outcome", (), {"run_id": "child-run-1"})()
    active = ActiveDelegation(
        SubagentRequest(
            delegation_id="delegation-1",
            parent_run_id="parent-run-1",
            task="inspect",
        )
    )
    active.budget = effective_budget(active.request.budget)

    result = _result_from_child(active, child, "done")

    assert result.status is SubagentStatus.COMPLETED
    assert result.evidence[0].source == "tool:read"
    assert result.usage == SubagentUsage(input_tokens=8, output_tokens=2)
    assert result.artifact is not None
    assert result.artifact.ref == "/tmp/report.txt"


@pytest.mark.integration
async def test_real_fake_client_child_returns_structured_result_without_transcript() -> None:
    child = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(
                FakeClient(
                    steps=[
                        {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "read-1",
                                    "name": "read",
                                    "args": {"file_path": "report.txt"},
                                }
                            ],
                        },
                        {"content": "报告已核验"},
                    ],
                    usage={"input_tokens": 15, "output_tokens": 4},
                ),
                context_window=2_000,
                output_reserve=100,
                reserve_tokens=50,
            ),
            tools=[_ArtifactTool()],
        ),
        EventBus(),
        store=None,
    )
    request = SubagentRequest(
        delegation_id="delegation-real-fake",
        parent_run_id="parent-run",
        task="检查报告",
        budget=SubagentBudget(max_turns=4, max_tool_calls=4),
    )

    result = await SerialSubagentRunner(lambda _request: child).execute(request)

    assert result.summary == "报告已核验"
    assert result.evidence[0].source == "tool:read"
    assert result.evidence[0].locator == "report.txt"
    assert result.usage == SubagentUsage(input_tokens=30, output_tokens=8)
    assert result.artifact is not None
    assert result.artifact.ref == "artifact-report-1"
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "tool_calls" not in serialized
    assert "observed fact\n" * 2 not in serialized
