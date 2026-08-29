"""Transcript 的布局缓存与视口物化。"""

from __future__ import annotations

from bisect import bisect_right

from ..presentation.blocks import AssistantBlock, Component
from ..presentation.primitives import RichLine


class TranscriptLayoutMixin:
    """将块布局、缓存和可见窗口算法从 Transcript 容器中分离。"""

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
        """以无界高度渲染全部块。"""
        return self._rows(width)[0]

    def all_lines(self, width: int) -> list[str]:
        """以无界高度渲染全部块的纯文本。"""
        return list(self.iter_lines(width))

    def iter_lines(self, width: int):
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
        """只物化视口及 overscan 范围内的块，维护行到块映射。"""
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
                self.follow = True
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

        entries, total, transient_entry = self._layout_entries(width, transient)
        max_start = max(0, total - height)
        start = max_start if self.follow else min(self._scroll_top, max_start)
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
        self._line_blocks = [owner for _, _, owner in visible_pairs]
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
                height = 0 if isinstance(block, AssistantBlock) and not block.has_body else 1
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
        self._range_starts = [start for _, start, _, _ in entries]
        return entries, cursor, transient_entry
