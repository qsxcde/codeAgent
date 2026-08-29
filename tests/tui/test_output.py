"""Large tool output preview, paging, and export tests."""

from pathlib import Path

from codeagent.app.tui.presentation.output import OutputBuffer, OutputMetadata
from codeagent.core.contracts.messages import ToolResult
from codeagent.app.tui.state.model import TuiModel
from codeagent.core.contracts.events import AgentEvent, EventType


def test_tool_result_carries_non_persistent_output_statistics() -> None:
    result = ToolResult("call-1", "a\nb\n", name="bash")
    assert result.total_bytes == len("a\nb\n".encode())
    assert result.total_lines == 2
    assert result.shown_lines == 2
    assert result.truncated_by is None


def test_output_buffer_shows_head_tail_preview_and_page_cursor() -> None:
    content = "\n".join(f"line-{i}" for i in range(10))
    buffer = OutputBuffer(
        content,
        metadata=OutputMetadata(
            total_bytes=len(content.encode()),
            total_lines=10,
            shown_lines=10,
        ),
        page_size=3,
    )
    assert buffer.page_count == 4
    assert buffer.page == 1
    assert buffer.visible_lines == (1, 3)
    assert buffer.next_page() is True
    assert buffer.page == 2
    assert buffer.previous_page() is True
    assert buffer.page == 1


def test_output_buffer_marks_unrecoverable_truncation() -> None:
    buffer = OutputBuffer(
        "head\n...",
        metadata=OutputMetadata(
            total_bytes=100,
            total_lines=20,
            shown_lines=2,
            truncated_by="bytes",
        ),
    )
    assert buffer.truncated is True
    assert "不完整" in buffer.diagnostic
    assert buffer.can_export is False


def test_output_buffer_can_export_truncated_result_from_existing_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "complete.txt"
    artifact.write_text("complete artifact", encoding="utf-8")
    buffer = OutputBuffer(
        "preview",
        metadata=OutputMetadata(
            total_bytes=100,
            total_lines=10,
            shown_lines=1,
            truncated_by="tool_bytes",
            completeness="truncated",
            artifact_path=str(artifact),
            source="structured",
        ),
    )

    assert buffer.can_export is True
    exported = buffer.export(tmp_path / "exported.txt")
    assert exported.read_text(encoding="utf-8") == "complete artifact"


def test_output_buffer_infers_truncation_from_runtime_marker() -> None:
    buffer = OutputBuffer("line-1\n[已截断] 达到上限\n")

    assert buffer.truncated is True
    assert buffer.can_export is False


def test_structured_output_metadata_wins_over_conflicting_text_marker() -> None:
    buffer = OutputBuffer(
        "[输出已截断] literal content",
        metadata=OutputMetadata(
            total_bytes=28,
            total_lines=1,
            shown_lines=1,
            completeness="complete",
            source="structured",
        ),
    )

    assert buffer.truncated is False
    assert buffer.can_export is True


def test_structured_incomplete_output_reports_unavailable_recovery() -> None:
    buffer = OutputBuffer(
        "preview",
        metadata=OutputMetadata(
            total_bytes=1_000,
            total_lines=100,
            shown_lines=2,
            completeness="incomplete",
            truncated_by="request_budget",
            source="structured",
        ),
    )

    assert buffer.truncated is True
    assert "request_budget" in buffer.diagnostic
    assert buffer.can_export is False


def test_output_buffer_reads_tool_line_range_marker() -> None:
    buffer = OutputBuffer("[1-2/10 行]\nline-1\nline-2\n")

    assert buffer.metadata.total_lines == 10
    assert buffer.metadata.shown_lines == 2
    assert buffer.truncated is True


def test_tool_result_infers_common_truncation_markers() -> None:
    from codeagent.core.contracts.messages import ToolResult

    result = ToolResult("call-1", "head\n… 输出已截断(条目超限) …")

    assert result.truncated_by == "tool"


def test_output_buffer_exports_available_original_without_model_call(tmp_path: Path) -> None:
    buffer = OutputBuffer("a\nb\n", page_size=1)
    path = buffer.export(tmp_path / "tool-output.txt")
    assert path.read_text() == "a\nb\n"
    assert buffer.artifact_path == str(path)
    buffer.cleanup()
    assert not path.exists()


def test_output_paging_does_not_change_message_content() -> None:
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="run"))
    model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"id": "call-1", "name": "bash", "args": {}}],
        )
    )
    content = "\n".join(f"line-{i}" for i in range(5))
    model.apply(
        AgentEvent(
            EventType.TOOL_RESULT,
            payload=content,
            metadata={
                "tool_call_id": "call-1",
                "status": "ok",
                "total_lines": 5,
                "shown_lines": 5,
                "total_bytes": len(content.encode()),
                "page_size": 2,
            },
        )
    )
    block = model.transcript.blocks[-1]
    assert model.page_output(1, "call-1") is True
    assert block.result == content
    assert block.output_buffer is not None and block.output_buffer.page == 2
