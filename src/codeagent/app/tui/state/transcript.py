"""TUI Transcript：块顺序、布局缓存、滚动与点击映射。"""

from __future__ import annotations

from collections import OrderedDict

from ..presentation.blocks import Component
from ..presentation.primitives import RichLine
from .transcript_layout import TranscriptLayoutMixin
from .transcript_progressive import ProgressiveTranscriptMixin


class Transcript(ProgressiveTranscriptMixin, TranscriptLayoutMixin, Component):
    """聊天区视口:有序子块 + 滚动状态(follow-end)+ 行→块映射(点击命中)。

    滚动语义(对应 spec「alt 屏渲染与滚动」):
    - ``follow=True`` 跟底(新内容自动可见);上滚解除跟随;滚到底部恢复跟随;
    - ``block_at(relative_y)`` 把视口行号映射回所属块(design D4,供工具点击折叠)。
    """

    def __init__(self, *, cache_capacity: int = 512, max_width_variants: int = 3) -> None:
        self._blocks: list[Component] = []
        self.follow = True
        self._scroll_top = 0
        self._line_blocks: list[Component | None] = []
        self._cache_capacity = max(1, int(cache_capacity))
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

    def append(self, block: Component) -> None:
        self._blocks.append(block)

    def remove(self, block: Component) -> None:
        """移除一个块并清理其所有宽度/revision 布局缓存。"""
        self._blocks.remove(block)
        block_id = id(block)
        for key in list(self._layout_cache):
            if key[0] == block_id:
                del self._layout_cache[key]
        self.layout_index = []
        self._range_starts = []
        self._line_blocks = []

    def clear(self) -> None:
        """清空聊天区(/clear 命令):重置块与滚动状态。"""
        self._blocks.clear()
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

    @property
    def new_output_count(self) -> int:
        """用户离开底部后累积的新输出块数量。"""
        return self._new_output_count

    @property
    def blocks(self) -> list[Component]:
        return list(self._blocks)

    @property
    def cache_entries(self) -> int:
        """Return the number of materialized layout cache entries."""
        return len(self._layout_cache)

    def block_at(self, relative_y: int) -> Component | None:
        """返回视口第 relative_y 行所属的块(越界 / 空返回 None)。"""
        if 0 <= relative_y < len(self._line_blocks):
            return self._line_blocks[relative_y]
        return None

    def scroll(self, delta: int) -> None:
        """按 delta 行滚动;正数上滚(朝向历史,解除跟随),负数下滚(朝向底部)。"""
        if delta > 0:
            self.follow = False
        self._scroll_top = max(0, self._scroll_top - delta)

    def scroll_to_bottom(self) -> None:
        self.follow = True
        self._scroll_top = 0
        self._new_output_count = 0
