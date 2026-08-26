"""TUI Transcript：块顺序、布局缓存、滚动与点击映射。"""

from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Iterator

from codeagent.app.tui.blocks import AssistantBlock, Component
from codeagent.app.tui.primitives import RichLine


class Transcript(Component):
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

    def _cache_lookup(self, block: Component, width: int) -> list[RichLine] | None:
        key = (id(block), width, int(getattr(block, "revision", 0)))
        if key not in self._layout_cache:
            return None
        rendered = self._layout_cache.pop(key)
        self._layout_cache[key] = rendered
        self.cache_hits += 1
        return rendered

    def _cache_store(self, block: Component, width: int, rendered: list[RichLine]) -> None:
        block_id = id(block)
        revision = int(getattr(block, "revision", 0))
        # A revision supersedes every older representation of this block.
        for key in list(self._layout_cache):
            if key[0] == block_id and key[2] != revision:
                del self._layout_cache[key]
        key = (block_id, width, revision)
        self._layout_cache.pop(key, None)
        self._layout_cache[key] = rendered
        same_revision = [
            item for item in self._layout_cache
            if item[0] == block_id and item[2] == revision
        ]
        while len(same_revision) > self._max_width_variants:
            old_key = same_revision.pop(0)
            self._layout_cache.pop(old_key, None)
        while len(self._layout_cache) > self._cache_capacity:
            self._layout_cache.popitem(last=False)

    def _render_cached(self, block: Component, width: int) -> list[RichLine]:
        rendered = self._cache_lookup(block, width)
        if rendered is not None:
            return rendered
        rendered = block.render(width)
        self._cache_store(block, width, rendered)
        self.cache_misses += 1
        return rendered

    def _rows(
        self, width: int, transient: Component | None = None
    ) -> tuple[list[RichLine], list[Component | None]]:
        """构造内容行与点击映射；块间空行、瞬态行均不命中点击。"""
        rows: list[RichLine] = []
        owners: list[Component | None] = []
        persistent: list[tuple[Component, list[RichLine]]] = []
        for block in self._blocks:
            rendered = self._render_cached(block, width)
            if rendered:
                persistent.append((block, rendered))
        self.layout_index = []
        cursor = 0
        for index, (block, rendered) in enumerate(persistent):
            if index:
                rows.append([])
                owners.append(None)
                cursor += 1
            start = cursor
            rows.extend(rendered)
            owners.extend([block] * len(rendered))
            cursor += len(rendered)
            self.layout_index.append((start, cursor, block))
        if transient is not None:
            rendered = transient.render(width)
            if rendered:
                if rows:
                    rows.append([])
                    owners.append(None)
                rows.extend(rendered)
                owners.extend([None] * len(rendered))
        return rows, owners

    def all_rich(self, width: int) -> list[RichLine]:
        """以无界高度渲染全部块(供退出文档 / 视口裁剪)。"""
        return self._rows(width)[0]

    def all_lines(self, width: int) -> list[str]:
        """以无界高度渲染全部块的纯文本(退出文档,design D6)。"""
        return list(self.iter_lines(width))

    def iter_lines(self, width: int) -> Iterator[str]:
        """按顶层块逐行生成完整退出文档，避免先构造超大 list。"""
        first = True
        for block in self._blocks:
            rendered = self._render_cached(block, width)
            if not rendered:
                continue
            if not first:
                yield ""
            first = False
            for line in rendered:
                yield "".join(span.text for span in line)

    def render(
        self, width: int, height: int, transient: Component | None = None
    ) -> list[RichLine]:
        """只物化视口及 overscan 范围内的块，维护行→块映射。"""
        height = max(0, height)
        if not self.follow and len(self._blocks) > self._last_block_count:
            self._new_output_count += len(self._blocks) - self._last_block_count

        transient_rendered: list[RichLine] = []
        entries: list[tuple[Component, int, int, list[RichLine] | None]] = []
        total = 0
        start = 0
        for _ in range(2):
            entries, total, transient_entry = self._layout_entries(width, transient)
            max_start = max(0, total - height)
            if not self.follow and self._scroll_top >= max_start:
                self.follow = True  # 滚到底部恢复跟随
            start = max_start if self.follow else min(self._scroll_top, max_start)
            self._scroll_top = start
            window_start = max(0, start - self.overscan)
            window_end = min(total, start + height + self.overscan)
            changed = False
            for block, block_start, block_end, rendered in entries:
                if rendered is None and block_end > window_start and block_start < window_end:
                    self._cache_block(block, width)
                    changed = True
            if transient_entry is not None:
                _, transient_start, transient_end, _ = transient_entry
                if transient_end > window_start and transient_start < window_end:
                    transient_rendered = transient.render(width) if transient is not None else []
            if not changed:
                break

        # Materialization can change a block's height; use the final layout for
        # the visible slice and its click owners.
        entries, total, transient_entry = self._layout_entries(width, transient)
        max_start = max(0, total - height)
        if self.follow:
            start = max_start
        else:
            start = min(self._scroll_top, max_start)
        self._scroll_top = start
        visible_end = start + height
        visible_pairs: list[tuple[int, RichLine, Component | None]] = []
        first_entry = max(0, bisect_right(self._range_starts, start) - 1)
        for entry_index in range(first_entry, len(entries)):
            block, block_start, block_end, rendered = entries[entry_index]
            if block_start - 1 >= visible_end and entry_index > first_entry:
                break
            if rendered is None:
                continue
            if entry_index:
                separator = block_start - 1
                if start <= separator < visible_end:
                    visible_pairs.append((separator, [], None))
            for index, line in enumerate(rendered, start=block_start):
                if start <= index < visible_end:
                    visible_pairs.append((index, line, block))
        if transient_entry is not None:
            _, transient_start, _, _ = transient_entry
            if entries:
                separator = transient_start - 1
                if start <= separator < visible_end:
                    visible_pairs.append((separator, [], None))
            for index, line in enumerate(transient_rendered, start=transient_start):
                if start <= index < visible_end:
                    visible_pairs.append((index, line, None))
        visible_pairs.sort(key=lambda item: item[0])
        visible = [line for _, line, _ in visible_pairs]
        owners = [owner for _, _, owner in visible_pairs]
        self._line_blocks = owners
        self.visible_range = (start, min(total, start + len(visible)))
        self.overscan_range = (
            max(0, start - self.overscan),
            min(total, start + height + self.overscan),
        )
        self._last_total = total
        self._last_block_count = len(self._blocks)
        if self.follow:
            self._new_output_count = 0
        return visible

    def _cache_block(self, block: Component, width: int) -> list[RichLine]:
        return self._render_cached(block, width)

    def _layout_entries(
        self, width: int, transient: Component | None
    ) -> tuple[
        list[tuple[Component, int, int, list[RichLine] | None]],
        int,
        tuple[Component, int, int, list[RichLine] | None] | None,
    ]:
        entries: list[tuple[Component, int, int, list[RichLine] | None]] = []
        cursor = 0
        self.layout_index = []
        self._range_starts = []
        for block in self._blocks:
            key = (id(block), width, int(getattr(block, "revision", 0)))
            rendered = self._layout_cache.get(key)
            if rendered is None and key not in self._layout_cache:
                # A single row is a conservative estimate until a visible
                # block is materialized; empty assistant blocks are free.
                height = 0 if isinstance(block, AssistantBlock) and not block.body else 1
                if height == 0:
                    continue
            else:
                if not rendered:
                    continue
                height = len(rendered)
            if entries:
                cursor += 1
            block_start = cursor
            block_end = block_start + height
            entries.append((block, block_start, block_end, rendered))
            self.layout_index.append((block_start, block_end, block))
            cursor = block_end
        transient_entry = None
        if transient is not None:
            if entries:
                cursor += 1
            transient_entry = (transient, cursor, cursor + 1, None)
            cursor += 1
        # ``layout_index`` is an index of the current estimates, not a cache
        # of rendered rows; callers can use it before every block is painted.
        self._range_starts = [start for _, start, _, _ in entries]
        return entries, cursor, transient_entry

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


