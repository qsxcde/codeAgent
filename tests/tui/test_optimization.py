"""Regression tests for bounded TUI rendering and lifecycle coordination."""

from __future__ import annotations

from codeagent.app.tui.presentation.blocks import AssistantBlock, Component, ToolCallBlock
from codeagent.app.tui.rendering.coordinator import TuiEventBuffer
from codeagent.app.tui.state.transcript import Transcript
from codeagent.core.events import AgentEvent, EventType


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


def test_restore_cost_counts_large_content_even_when_message_count_is_small():
    from codeagent.app.tui.session.coordinator import TuiSessionCoordinator
    from codeagent.core.messages import Message

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
