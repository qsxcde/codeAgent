"""Offline integration coverage for the governed tool-result pipeline."""

from __future__ import annotations

from pydantic import BaseModel

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.composition.model.port import ChatModelPort
from codeagent.app.composition.tools.adapter import adapt_tools
from codeagent.app.tui.presentation.blocks import ToolCallBlock
from codeagent.app.tui.presentation.output import OutputBuffer
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.core.contracts.events import EventType
from codeagent.session import AgentSession, EventBus
from codeagent.session.persistence.jsonl import JsonFileStore
from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import OutputPolicy, GovernedText, govern_text


class _ReportArgs(BaseModel):
    label: str


class _ReportTool(AtomicTool):
    name = "report"
    description = "return a bounded report"
    Args = _ReportArgs

    def _invoke(self, args: _ReportArgs) -> GovernedText:
        content = "\n".join(f"{args.label}-{index}" for index in range(200))
        return govern_text(
            content,
            OutputPolicy(max_bytes=800, max_lines=100, direction="head"),
            path=f"{args.label}.txt",
            continuation=f"rerun report with label={args.label}",
        )


async def test_tool_result_facts_survive_pipeline_and_request_budget(tmp_path) -> None:
    client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {"name": "report", "id": "call-a", "args": {"label": "a"}},
                    {"name": "report", "id": "call-b", "args": {"label": "b"}},
                ]
            },
            {"content": "done"},
        ]
    )
    store = JsonFileStore(tmp_path / "sessions")
    session = AgentSession(
        AgentLoopConfig(
            model=ChatModelPort(
                client,
                context_window=200,
                output_reserve=0,
                reserve_tokens=0,
                window_source="override",
            ),
            tools=adapt_tools([_ReportTool()]),
        ),
        EventBus(),
        store=store,
        session_id="governance",
    )
    events = []
    session.subscribe(events.append)

    await session.run("inspect reports")

    governed = session.context_diagnostics.tool_results
    assert len(governed) == 2
    assert all(item.action == "tool_lines" for item in governed)

    history = session.history
    tool_messages = [message for message in history if message.role == "tool"]
    assert [message.tool_call_id for message in tool_messages] == ["call-a", "call-b"]
    assert [message.tool_output.path for message in tool_messages] == [
        "a.txt",
        "b.txt",
    ]
    assert all(message.tool_output.is_truncated for message in tool_messages)

    result_events = [event for event in events if event.type == EventType.TOOL_RESULT]
    assert {event.metadata["tool_call_id"] for event in result_events} == {
        "call-a",
        "call-b",
    }
    assert all(event.metadata["output_metadata"]["completeness"] == "truncated" for event in result_events)

    persisted = JsonFileStore(tmp_path / "sessions").load_messages("governance")
    persisted_tools = [message for message in persisted if message.role == "tool"]
    assert [message.tool_call_id for message in persisted_tools] == ["call-a", "call-b"]
    assert persisted_tools[0].tool_output.path == "a.txt"

    second_request_tools = [
        message for message in client.call_history[1]["messages"] if message["role"] == "tool"
    ]
    assert len(second_request_tools) == 2
    assert all("工具结果元数据" in message["content"] for message in second_request_tools)
    assert all("工具结果已按请求预算裁剪" in message["content"] for message in second_request_tools)

    block = ToolCallBlock("report", {"label": "a"}, call_id="call-a")
    block.set_result(
        persisted_tools[0].content,
        output_metadata=persisted_tools[0].tool_output.to_dict(),
    )
    assert block.output_buffer is not None
    assert block.output_buffer.truncated
    assert not block.output_buffer.can_export
    assert "无法恢复" in block.output_buffer.diagnostic

    projection = OutputBuffer(
        persisted_tools[0].content,
        metadata=persisted_tools[0].tool_output,
    )
    assert projection.metadata.path == "a.txt"
    assert projection.metadata.continuation.startswith("rerun report")
