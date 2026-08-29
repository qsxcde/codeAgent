"""长会话视口、锚点和工具结果分页回归。"""

from __future__ import annotations

import pytest

from codeagent.app.tui.benchmark.benchmark import BenchmarkConfig, build_fixture, run_benchmark
from codeagent.app.tui.presentation.blocks import Component
from codeagent.app.tui.presentation.output import OutputBuffer, OutputMetadata
from codeagent.app.tui.presentation.primitives import Span, rich_to_plain
from codeagent.app.tui.state.transcript import Transcript


class _VariableBlock(Component):
    def __init__(self, name: str, lines: int = 1) -> None:
        super().__init__()
        self.name = name
        self.lines = lines
        self.render_calls = 0

    def render(self, width: int) -> list[list[Span]]:
        self.render_calls += 1
        return [[Span(f"{self.name}:{index}")] for index in range(self.lines)]

    def resize(self, lines: int) -> None:
        self.lines = lines
        self.touch()


def test_long_history_keeps_layout_work_near_the_viewport() -> None:
    transcript = Transcript()
    blocks = [_VariableBlock(str(index)) for index in range(5_000)]
    for block in blocks:
        transcript.append(block)

    transcript.render(80, 10)

    assert transcript.layout_stats["blocks_inspected"] <= 64
    assert sum(block.render_calls for block in blocks) <= 32


def test_reading_anchor_survives_height_change_before_viewport() -> None:
    transcript = Transcript()
    blocks = [_VariableBlock(str(index)) for index in range(40)]
    for block in blocks:
        transcript.append(block)

    transcript.render(80, 8)
    transcript.scroll(12)
    transcript.render(80, 8)
    anchor = next(
        block for row in range(8) if (block := transcript.block_at(row)) is not None
    )
    blocks[0].resize(12)

    transcript.render(80, 8)

    assert transcript.block_at(0) is anchor


def test_output_buffer_reads_only_requested_page_with_structured_metadata() -> None:
    class _NoSplit(str):
        def splitlines(self, *args, **kwargs):
            raise AssertionError("page rendering split the complete output")

    content = _NoSplit("".join(f"line {index}\n" for index in range(10_000)))
    buffer = OutputBuffer(
        content,
        metadata=OutputMetadata(
            total_lines=10_000,
            shown_lines=10_000,
            completeness="complete",
            source="structured",
        ),
        page_size=40,
    )

    assert buffer.page_count == 250
    assert buffer.current_page == [f"line {index}" for index in range(40)]
    buffer.next_page()
    assert buffer.current_page == [f"line {index}" for index in range(40, 80)]
    buffer.page = buffer.page_count
    assert buffer.current_page == [f"line {index}" for index in range(9_960, 10_000)]
    assert buffer.next_page() is False
    assert buffer.previous_page() is True
    assert buffer.current_page == [f"line {index}" for index in range(9_920, 9_960)]


def test_index_updates_append_remove_clear_and_duplicate_revision_without_rebuild() -> None:
    transcript = Transcript()
    blocks = [_VariableBlock(str(index)) for index in range(130)]
    for block in blocks:
        transcript.append(block)

    transcript.render(80, 10)
    blocks[65].resize(3)
    transcript.render(80, 10)
    blocks[65].touch()
    transcript.render(80, 10)

    transcript.remove(blocks[64])
    assert blocks[64] not in transcript.blocks
    with pytest.raises(ValueError):
        transcript.remove(blocks[64])
    transcript.clear()

    assert transcript.block_count == 0
    assert transcript.layout_stats["blocks_inspected"] == 0
    assert transcript.cache_entries == 0


def test_richline_cache_has_a_row_budget_in_addition_to_entry_budget() -> None:
    transcript = Transcript(cache_capacity=128)
    for index in range(20):
        transcript.append(_VariableBlock(str(index), lines=10))

    transcript.all_rich(80)

    assert transcript.cache_rows <= transcript.cache_line_capacity


def test_optimized_view_matches_complete_render_oracle() -> None:
    fixture = build_fixture(BenchmarkConfig(scenario="history", history_blocks=1_000))

    visible = rich_to_plain(fixture.model.render(80, 24))
    complete = list(fixture.model.transcript.iter_lines(80))

    assert visible == complete[-24:]


@pytest.mark.parametrize("block_count", [1_000, 5_000, 10_000])
def test_long_fixture_has_bounded_view_metrics(block_count: int) -> None:
    result = run_benchmark(
        BenchmarkConfig(scenario="history", history_blocks=block_count, iterations=1)
    )

    assert result.counters["block_count"] == block_count
    assert result.counters["blocks_inspected"] <= 128
    assert result.counters["blocks_materialized"] <= 32
    assert result.counters["cache_rows"] <= 64
    assert result.counters["index_updates"] >= 1
