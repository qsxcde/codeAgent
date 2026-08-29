from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from codeagent.core.contracts.messages import (
    OutputCompleteness,
    ToolCall,
    ToolExecutionStatus,
    ToolOutputMetadata,
    ToolResult,
)
from codeagent.core.execution.result import normalize_tool_result
from codeagent.core.execution.state import ToolOperation


def test_tool_output_metadata_is_immutable_and_serializable() -> None:
    metadata = ToolOutputMetadata(
        completeness=OutputCompleteness.TRUNCATED,
        total_bytes=100,
        total_lines=20,
        shown_bytes=40,
        shown_lines=8,
        truncated_by="tool_bytes",
        path="src/app.py",
        exit_code=0,
        duration_ms=12,
        stderr_summary="warning",
        change_summary="updated 2 lines",
        artifact_ref="artifact-1",
    )

    encoded = metadata.to_dict()

    assert encoded["completeness"] == "truncated"
    assert encoded["total_bytes"] == 100
    assert ToolOutputMetadata.from_dict(encoded) == metadata
    with pytest.raises(FrozenInstanceError):
        metadata.total_bytes = 1  # type: ignore[misc]


def test_structured_metadata_is_authoritative_over_content_markers() -> None:
    result = ToolResult(
        "call-1",
        "[输出已截断] but this is a literal file line",
        output_metadata=ToolOutputMetadata(
            completeness=OutputCompleteness.COMPLETE,
            total_bytes=45,
            total_lines=1,
            shown_bytes=45,
            shown_lines=1,
        ),
    )

    assert result.output_metadata.completeness == OutputCompleteness.COMPLETE
    assert result.truncated_by is None
    assert result.output_truncated is False


def test_normalize_tool_result_preserves_governed_fields() -> None:
    call = ToolCall("call-1", "read")
    operation = ToolOperation("operation-1", call.id, call.name)
    metadata = ToolOutputMetadata(
        completeness=OutputCompleteness.TRUNCATED,
        total_bytes=200,
        total_lines=20,
        shown_bytes=80,
        shown_lines=8,
        truncated_by="request_budget",
        path="README.md",
        range_start=10,
        range_end=17,
        change_summary="none",
    )
    source = ToolResult(
        call.id,
        "bounded",
        name="read",
        status=ToolExecutionStatus.OK,
        output_metadata=metadata,
    )

    result, _ = normalize_tool_result(call, "read", operation, source)

    assert result.output_metadata == metadata
    assert result.total_bytes == 200
    assert result.shown_lines == 8
    assert result.truncated_by == "request_budget"
    assert result.artifact_path is None


def test_normalize_legacy_string_marks_completeness_unknown() -> None:
    call = ToolCall("call-1", "legacy")
    operation = ToolOperation("operation-1", call.id, call.name)

    result, _ = normalize_tool_result(call, "legacy", operation, "plain output")

    assert result.output_metadata.completeness == OutputCompleteness.UNKNOWN
    assert result.output_metadata.source == "legacy"
