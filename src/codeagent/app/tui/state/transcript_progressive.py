"""协作式 Transcript 视口准备。"""

from __future__ import annotations

import asyncio
from bisect import bisect_right

from ..presentation.blocks import AssistantBlock, Component
from ..presentation.primitives import RichLine


class ProgressiveTranscriptMixin:
    """在大布局准备期间把控制权让回事件循环。"""

    async def render_progressive(
        self,
        width: int,
        height: int,
        transient: Component | None = None,
        *,
        yield_every: int = 32,
    ) -> list[RichLine]:
        height = max(0, height)
        yield_every = max(1, yield_every)
        if not self.follow and len(self._blocks) > self._last_block_count:
            self._new_output_count += len(self._blocks) - self._last_block_count

        transient_rendered: list[RichLine] = []
        entries: list[tuple[Component, int, int, list[RichLine] | None]] = []
        total = 0
        for _ in range(2):
            entries, total, transient_entry = await self._layout_entries_progressive(
                width, transient, yield_every
            )
            max_start = max(0, total - height)
            if not self.follow and self._scroll_top >= max_start:
                self.follow = True
            start = max_start if self.follow else min(self._scroll_top, max_start)
            self._scroll_top = start
            window_start = max(0, start - self.overscan)
            window_end = min(total, start + height + self.overscan)
            changed = False
            for index, (block, block_start, block_end, rendered) in enumerate(entries):
                if rendered is None and block_end > window_start and block_start < window_end:
                    await self._cache_block_progressive(block, width, yield_every)
                    changed = True
                if (index + 1) % yield_every == 0:
                    await asyncio.sleep(0)
            if transient_entry is not None:
                _, transient_start, transient_end, _ = transient_entry
                if transient_end > window_start and transient_start < window_end:
                    transient_rendered = transient.render(width) if transient is not None else []
            if not changed:
                break

        entries, total, transient_entry = await self._layout_entries_progressive(
            width, transient, yield_every
        )
        return self._collect_visible_progressive(
            entries, total, height, transient_entry, transient_rendered
        )

    def _collect_visible_progressive(
        self,
        entries: list[tuple[Component, int, int, list[RichLine] | None]],
        total: int,
        height: int,
        transient_entry: tuple[Component, int, int, list[RichLine] | None] | None,
        transient_rendered: list[RichLine],
    ) -> list[RichLine]:
        start = max(0, total - height) if self.follow else min(self._scroll_top, max(0, total - height))
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

    async def _layout_entries_progressive(
        self,
        width: int,
        transient: Component | None,
        yield_every: int,
    ) -> tuple[
        list[tuple[Component, int, int, list[RichLine] | None]],
        int,
        tuple[Component, int, int, list[RichLine] | None] | None,
    ]:
        entries: list[tuple[Component, int, int, list[RichLine] | None]] = []
        cursor = 0
        self.layout_index = []
        self._range_starts = []
        for index, block in enumerate(self._blocks):
            key = (id(block), width, int(getattr(block, "revision", 0)))
            rendered = self._layout_cache.get(key)
            if rendered is None and key not in self._layout_cache:
                has_body = isinstance(block, AssistantBlock) and block.has_body
                height = 1 if has_body or not isinstance(block, AssistantBlock) else 0
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
            if (index + 1) % yield_every == 0:
                await asyncio.sleep(0)
        transient_entry = None
        if transient is not None:
            if entries:
                cursor += 1
            transient_entry = (transient, cursor, cursor + 1, None)
            cursor += 1
        self._range_starts = [start for _, start, _, _ in entries]
        return entries, cursor, transient_entry

    async def _cache_block_progressive(
        self, block: Component, width: int, yield_every: int
    ) -> list[RichLine]:
        """Render one visible block cooperatively when it supports chunking."""
        progressive = getattr(block, "render_progressive", None)
        if progressive is None:
            return self._cache_block(block, width)
        revision = int(getattr(block, "revision", 0))
        rendered = await progressive(width, yield_every=yield_every)
        if revision == int(getattr(block, "revision", 0)):
            self._cache_store(block, width, rendered)
        self.cache_misses += 1
        return rendered
