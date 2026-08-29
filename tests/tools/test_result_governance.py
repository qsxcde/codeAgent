from __future__ import annotations

from codeagent.tools.shared.governance import (
    OutputPolicy,
    GovernedText,
    govern_text,
)


def test_govern_text_keeps_bounded_head_and_structured_statistics() -> None:
    governed = govern_text(
        "\n".join(f"line-{i}" for i in range(10)),
        OutputPolicy(max_bytes=1_000, max_lines=3, direction="head"),
    )

    assert isinstance(governed, GovernedText)
    assert governed.startswith("line-0\nline-1\nline-2")
    assert "输出已截断" in governed
    assert governed.output_metadata["completeness"] == "truncated"
    assert governed.output_metadata["total_lines"] == 10
    assert governed.output_metadata["shown_lines"] == 3
    assert governed.output_metadata["truncated_by"] == "tool_lines"


def test_govern_text_tail_preserves_utf8_boundary_and_reason() -> None:
    governed = govern_text(
        "开头\n" + "x" * 20 + "\n结尾",
        OutputPolicy(max_bytes=10, max_lines=100, direction="tail"),
    )

    assert isinstance(governed, str)
    assert "结尾" in governed
    assert governed.output_metadata["completeness"] == "truncated"
    assert governed.output_metadata["truncated_by"] == "tool_bytes"
    assert governed.output_metadata["total_bytes"] > governed.output_metadata["shown_bytes"]


def test_govern_text_complete_result_has_no_marker_or_truncation() -> None:
    governed = govern_text(
        "hello\nworld",
        OutputPolicy(max_bytes=100, max_lines=10, direction="head"),
    )

    assert governed == "hello\nworld"
    assert governed.output_metadata["completeness"] == "complete"
    assert governed.output_metadata["truncated_by"] is None
