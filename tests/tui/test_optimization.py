"""Regression tests for bounded TUI rendering and lifecycle coordination."""

from __future__ import annotations

from codeagent.app.tui.presentation.blocks import AssistantBlock, Component, ToolCallBlock
from codeagent.app.tui.presentation.md_renderer import MAX_MD_RENDER_LEN
from codeagent.app.tui.rendering.coordinator import TuiEventBuffer
from codeagent.app.tui.state.transcript import Transcript
from codeagent.core.contracts.events import AgentEvent, EventType


class _Block(Component):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.calls = 0

    def render(self, width: int):
        self.calls += 1
        return [[self.text[: max(1, width)]]]


def test_transcript_cache_is_bounded_and_revision_aware():
    transcript = Transcript(cache_capacity=2, max_width_variants=1)
    first = _Block("first")
    second = _Block("second")
    transcript.append(first)
    transcript.append(second)

    transcript.render(20, 10)
    transcript.render(30, 10)
    assert transcript.cache_entries <= 2

    first.touch()
    transcript.render(30, 10)
    assert transcript.cache_entries <= 2
    assert first.calls >= 2

    transcript.remove(second)
    assert second not in transcript.blocks
    transcript.clear()
    assert transcript.cache_entries == 0


def test_transcript_click_mapping_survives_resize_and_tool_expansion():
    transcript = Transcript()
    transcript.append(_Block("before"))
    tool = ToolCallBlock("bash", {"command": "printf ok"}, call_id="call-1")
    tool.set_result("ok\nsecond line")
    transcript.append(tool)

    transcript.render(60, 4)
    assert any(transcript.block_at(row) is tool for row in range(4))

    tool.toggle_expand()
    transcript.render(30, 8)
    assert any(transcript.block_at(row) is tool for row in range(8))


def test_adjacent_stream_deltas_flush_at_frame_boundary_without_crossing_structure():
    applied: list[tuple[str, object]] = []
    buffer = TuiEventBuffer(lambda event: applied.append((event.type, event.payload)))

    buffer.push(AgentEvent(EventType.TEXT_DELTA, "a"))
    buffer.push(AgentEvent(EventType.TEXT_DELTA, "b"))
    assert applied == []

    buffer.flush()
    assert applied == [(EventType.TEXT_DELTA, "ab")]

    buffer.push(AgentEvent(EventType.THINKING_DELTA, "reason"))
    buffer.push(AgentEvent(EventType.TOOL_CALL, [{"name": "bash"}]))
    buffer.push(AgentEvent(EventType.TEXT_DELTA, "after"))
    buffer.flush()
    assert [item[0] for item in applied] == [
        EventType.TEXT_DELTA,
        EventType.THINKING_DELTA,
        EventType.TOOL_CALL,
        EventType.TEXT_DELTA,
    ]


def test_stream_buffer_flushes_large_batches_without_losing_text():
    """高频小增量达到批次上限时分段归约,不让单个 payload 无界增长。"""
    applied: list[tuple[str, object]] = []
    buffer = TuiEventBuffer(lambda event: applied.append((event.type, event.payload)))

    total = TuiEventBuffer.MAX_PENDING_CHARS * 2 + 17
    for _ in range(total):
        buffer.push(AgentEvent(EventType.TEXT_DELTA, "x"))
    buffer.flush()

    assert len(applied) >= 3
    assert "".join(str(payload) for _, payload in applied) == "x" * total
    assert buffer.max_pending_chars <= TuiEventBuffer.MAX_PENDING_CHARS


def test_streaming_markdown_parses_only_newly_stable_lines():
    """连续稳定行只调用 Markdown 渲染器处理新增行和当前尾部。"""
    calls: list[str] = []

    def renderer(text: str, width: int):
        calls.append(text)
        return [[text]]

    block = AssistantBlock(md_renderer=renderer)
    for index in range(20):
        block.append_text(f"line {index}\n")
        block.render(40)
    block.append_text("tail")
    block.render(40)

    assert calls == [*(f"line {index}" for index in range(20)), "tail"]


def test_collapsed_large_tool_result_uses_metadata_without_scanning_body():
    """折叠大结果只读取摘要 metadata,不在渲染路径扫描完整正文。"""
    class _NoScan(str):
        def splitlines(self, *args, **kwargs):
            raise AssertionError("collapsed summary scanned the full result")

    block = ToolCallBlock("bash", {"command": "cat large.txt"})
    block.set_result(
        "first line\n" + "x" * 200_000,
        output_metadata={
            "source": "structured",
            "completeness": "complete",
            "total_bytes": 200_010,
            "total_lines": 2,
            "shown_lines": 2,
            "exit_code": 0,
        },
    )
    block.result = _NoScan(block.result)

    lines = block.render(80)

    assert "Ran command" in "".join(span.text for line in lines for span in line)


def test_collapsed_legacy_tool_result_remains_compatible():
    """旧工具结果没有结构化 metadata 时仍能以有限摘要安全渲染。"""
    block = ToolCallBlock("bash", {"command": "printf ok"})
    block.set_result("first line\n" + "x" * 100_000)

    lines = block.render(80)

    plain = "".join(span.text for line in lines for span in line)
    assert "Ran command" in plain
    assert len(plain) < 1_000


def test_restore_cost_counts_large_content_even_when_message_count_is_small():
    from codeagent.app.tui.session.coordinator import TuiSessionCoordinator
    from codeagent.core.contracts.messages import Message

    cost = TuiSessionCoordinator._restore_cost(
        [Message(role="assistant", content="x" * 200_000)]
    )
    assert cost.message_count == 1
    assert cost.text_chars == 200_000
    assert cost.requires_background is True


def test_streaming_markdown_reuses_completed_prefix_and_corrects_at_terminal():
    calls: list[str] = []

    def renderer(text: str, width: int):
        calls.append(text)
        return [[text]]

    block = AssistantBlock(md_renderer=renderer)
    block.append_text("第一行\n")
    block.render(40)
    block.append_text("第二行")
    block.render(40)

    assert calls == ["第一行", "第二行"]
    block.finalize()
    block.render(40)
    assert calls[-1] == "第一行\n第二行"


def test_streaming_markdown_terminal_frame_matches_full_render_after_resize():
    """流式最终帧在换宽后仍与完整 Markdown 基线完全一致。"""
    body = "# 标题\n- 一项 **粗体**\n\n```python\nprint(1)\n```\n尾部"
    streamed = AssistantBlock()
    for start in range(0, len(body), 3):
        streamed.append_text(body[start : start + 3])
        streamed.render(40)
    streamed.finalize()

    baseline = AssistantBlock()
    baseline.append_text(body)
    baseline.finalize()

    assert streamed.render(40) == baseline.render(40)
    assert streamed.render(24) == baseline.render(24)


def test_streaming_markdown_empty_and_unclosed_structures_finalize_once():
    """空正文、未闭合围栏和重复终态都保持可渲染且不重复内容。"""
    empty = AssistantBlock()
    empty.append_text("\n")
    empty.finalize()
    assert empty.render(40) == []

    unclosed = AssistantBlock()
    unclosed.append_text("```\nnot closed")
    assert unclosed.render(40)
    unclosed.finalize()
    first = unclosed.render(40)
    unclosed.finalize()
    assert unclosed.render(40) == first


def test_streaming_markdown_over_threshold_degrades_without_error():
    """超过 Markdown 解析阈值的活动正文仍可安全渲染。"""
    block = AssistantBlock()
    block.append_text("x" * (MAX_MD_RENDER_LEN + 1))

    lines = block.render(80)

    assert lines
