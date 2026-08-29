"""TUI Transcript：块顺序、布局缓存、滚动与点击映射。"""

from __future__ import annotations

from collections import OrderedDict

from ..presentation.blocks import Component
from ..presentation.primitives import RichLine
from .transcript_layout import TranscriptLayoutMixin
from .transcript_index import TranscriptLayoutIndex
from .transcript_progressive import ProgressiveTranscriptMixin


class Transcript(ProgressiveTranscriptMixin, TranscriptLayoutMixin, Component):
    """聊天区视口:有序子块 + 滚动状态(follow-end)+ 行→块映射(点击命中)。

    滚动语义(对应 spec「alt 屏渲染与滚动」):
    - ``follow=True`` 跟底(新内容自动可见);上滚解除跟随;滚到底部恢复跟随;
    - ``block_at(relative_y)`` 把视口行号映射回所属块(design D4,供工具点击折叠)。
    """

    def __init__(self, *, cache_capacity: int = 512, max_width_variants: int = 3) -> None:
        super().__init__()
        self._blocks: list[Component] = []
        self.follow = True
        self._scroll_top = 0
        self._line_blocks: list[Component | None] = []
        self._cache_capacity = max(1, int(cache_capacity))
        self._cache_line_capacity = max(64, self._cache_capacity * 8)
        self._max_width_variants = max(1, int(max_width_variants))
        self._layout_cache: OrderedDict[tuple[int, int, int], list[RichLine]] = OrderedDict()
        self._last_total = 0
        self._last_block_count = 0
        self._new_output_count = 0
        self.visible_range = (0, 0)
        self.overscan = 2
        self.layout_index: list[tuple[int, int, Component]] = []
        self._range_starts: list[int] = []
        self.overscan_range = (0, 0)
        self.cache_hits = 0
        self.cache_misses = 0
        self._layout_index = TranscriptLayoutIndex(max_width_variants=max_width_variants)
        self._anchor: tuple[int, int] | None = None
        self._restore_anchor = False
        self._last_width: int | None = None
        self.layout_stats = {
            "blocks_inspected": 0,
            "blocks_materialized": 0,
            "index_updates": 0,
        }

    def append(self, block: Component) -> None:
        self._blocks.append(block)
        self._layout_index.register(block)
        add_listener = getattr(block, "add_touch_listener", None)
        if add_listener is not None:
            add_listener(self._on_block_touched)

    def _on_block_touched(self, block: Component) -> None:
        self._layout_index.invalidate(block)
        token = self._layout_index.token_for(block)
        if token is not None:
            for key in list(self._layout_cache):
                if key[0] == token:
                    del self._layout_cache[key]
        if not self.follow and self._anchor is not None:
            self._restore_anchor = True

    def remove(self, block: Component) -> None:
        """移除一个块并清理其所有宽度/revision 布局缓存。"""
        removed_index = self._blocks.index(block)
        self._blocks.remove(block)
        remove_listener = getattr(block, "remove_touch_listener", None)
        if remove_listener is not None:
            remove_listener(self._on_block_touched)
        token = self._layout_index.token_for(block)
        if self._anchor is not None and self._anchor[0] == token:
            neighbors = self._blocks[removed_index:] + self._blocks[:removed_index]
            replacement = next(
                (self._layout_index.token_for(item) for item in neighbors), None
            )
            self._anchor = (replacement, 0) if replacement is not None else None
            self._restore_anchor = self._anchor is not None and not self.follow
        self._layout_index.unregister(block)
        for key in list(self._layout_cache):
            if key[0] == token:
                del self._layout_cache[key]
        self.layout_index = []
        self._range_starts = []
        self._line_blocks = []

    def clear(self) -> None:
        """清空聊天区(/clear 命令):重置块与滚动状态。"""
        for block in self._blocks:
            remove_listener = getattr(block, "remove_touch_listener", None)
            if remove_listener is not None:
                remove_listener(self._on_block_touched)
        self._blocks.clear()
        self._layout_index.clear()
        self.follow = True
        self._scroll_top = 0
        self._line_blocks = []
        self._layout_cache.clear()
        self._last_total = 0
        self._last_block_count = 0
        self._new_output_count = 0
        self.visible_range = (0, 0)
        self.layout_index = []
        self._range_starts = []
        self.overscan_range = (0, 0)
        self._anchor = None
        self._restore_anchor = False
        self._last_width = None
        self.layout_stats = {
            "blocks_inspected": 0,
            "blocks_materialized": 0,
            "index_updates": 0,
        }

    @property
    def new_output_count(self) -> int:
        """用户离开底部后累积的新输出块数量。"""
        return self._new_output_count

    @property
    def blocks(self) -> list[Component]:
        return list(self._blocks)

    @property
    def block_count(self) -> int:
        """Return the number of blocks without copying the transcript."""
        return len(self._blocks)

    def iter_blocks(self):
        """Iterate over blocks for read-only diagnostics without materializing a list."""
        return iter(self._blocks)

    @property
    def cache_entries(self) -> int:
        """Return the number of materialized layout cache entries."""
        return len(self._layout_cache)

    @property
    def cache_rows(self) -> int:
        """Return the number of cached RichLine rows without exposing content."""
        return sum(len(lines) for lines in self._layout_cache.values())

    @property
    def cache_line_capacity(self) -> int:
        """Return the approximate row budget used for RichLine eviction."""
        return self._cache_line_capacity

    def block_at(self, relative_y: int) -> Component | None:
        """返回视口第 relative_y 行所属的块(越界 / 空返回 None)。"""
        if 0 <= relative_y < len(self._line_blocks):
            return self._line_blocks[relative_y]
        return None

    def scroll(self, delta: int) -> None:
        """按 delta 行滚动;正数上滚(朝向历史,解除跟随),负数下滚(朝向底部)。"""
        if delta > 0:
            self.follow = False
            self._restore_anchor = False
        self._scroll_top = max(0, self._scroll_top - delta)

    def scroll_to_bottom(self) -> None:
        self.follow = True
        self._scroll_top = 0
        self._new_output_count = 0
        self._restore_anchor = False

    def _restore_anchor_start(self, width: int, height: int, total: int) -> int | None:
        if self.follow or not self._restore_anchor or self._anchor is None:
            return None
        token, local_row = self._anchor
        position = self._layout_index.position(width, token)
        if position is None:
            self._restore_anchor = False
            return None
        block_start, block_height, _ = position
        if block_height <= local_row:
            self._restore_anchor = False
            return None
        self._restore_anchor = False
        return max(0, min(block_start + local_row, max(0, total - height)))

    def _capture_anchor(self, width: int) -> None:
        if self.follow:
            self._anchor = None
            return
        for relative_row, block in enumerate(self._line_blocks):
            if block is None:
                continue
            token = self._layout_index.token_for(block)
            if token is None:
                continue
            absolute_row = self.visible_range[0] + relative_row
            mapped = self._layout_index.block_at(width, absolute_row)
            local_row = mapped[1] if mapped is not None and mapped[0] is block else 0
            self._anchor = (token, local_row)
            return
        self._anchor = None
