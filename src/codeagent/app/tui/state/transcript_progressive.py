"""协作式 Transcript 视口准备。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..presentation.primitives import RichLine


class ProgressiveTranscriptMixin:
    """在可见窗口准备期间把控制权让回事件循环。"""

    async def render_progressive(
        self,
        width: int,
        height: int,
        transient=None,
        *,
        yield_every: int = 32,
        is_current: Callable[[], bool] | None = None,
    ) -> list[RichLine]:
        height = max(0, height)
        width = max(1, width)
        yield_every = max(1, yield_every)
        if self._last_width != width and not self.follow:
            self._restore_anchor = True
        self._last_width = width
        if not self.follow and len(self._blocks) > self._last_block_count:
            self._new_output_count += len(self._blocks) - self._last_block_count
        transient_rendered = transient.render(width) if transient is not None else []
        self.layout_stats = {"blocks_inspected": 0, "blocks_materialized": 0, "index_updates": 0}
        before_updates = self._layout_index.update_count
        for _ in range(3):
            if is_current is not None and not is_current():
                return []
            persistent_total, total, start = self._geometry(width, height, transient_rendered)
            window_start = max(0, start - self.overscan)
            window_end = min(total, start + height + self.overscan)
            entries = self._layout_index.entries_from(width, window_start, window_end)
            self.layout_stats["blocks_inspected"] += len(entries)
            changed = False
            for index, (record, block_start, block_end, _) in enumerate(entries, start=1):
                if block_end > window_start and block_start < window_end:
                    if self._cache_lookup(record.block, width) is None:
                        await self._cache_block_progressive(record.block, width, yield_every)
                        self.layout_stats["blocks_materialized"] += 1
                        changed = True
                if index % yield_every == 0:
                    await asyncio.sleep(0)
                    if is_current is not None and not is_current():
                        return []
            if not changed:
                break

        persistent_total, total, start = self._geometry(width, height, transient_rendered)
        if is_current is not None and not is_current():
            return []
        self._last_total = total
        self.layout_stats["index_updates"] = self._layout_index.update_count - before_updates
        visible = self._collect_visible(
            width, height, persistent_total, total, start, transient_rendered, transient
        )
        self._last_block_count = len(self._blocks)
        if self.follow:
            self._new_output_count = 0
        return visible

    async def _cache_block_progressive(self, block, width: int, yield_every: int) -> list[RichLine]:
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
