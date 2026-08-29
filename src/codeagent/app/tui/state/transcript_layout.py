"""Transcript 的布局缓存与视口物化。"""

from __future__ import annotations

from ..presentation.primitives import RichLine


class TranscriptLayoutMixin:
    """将块布局、缓存和可见窗口算法从 Transcript 容器中分离。"""

    def _cache_key(self, block, width: int) -> tuple[int, int, int]:
        token = self._layout_index.token_for(block)
        if token is None:
            raise ValueError("block is not registered in transcript")
        return token, width, int(getattr(block, "revision", 0))

    def _cache_lookup(self, block, width: int) -> list[RichLine] | None:
        key = self._cache_key(block, width)
        if key not in self._layout_cache:
            return None
        rendered = self._layout_cache.pop(key)
        self._layout_cache[key] = rendered
        self.cache_hits += 1
        return rendered

    def _cache_store(self, block, width: int, rendered: list[RichLine]) -> None:
        key = self._cache_key(block, width)
        for old_key in list(self._layout_cache):
            if old_key[0] == key[0] and old_key[2] != key[2]:
                del self._layout_cache[old_key]
        self._layout_cache.pop(key, None)
        self._layout_cache[key] = rendered
        same_revision = [item for item in self._layout_cache if item[0] == key[0]]
        while len(same_revision) > self._max_width_variants:
            self._layout_cache.pop(same_revision.pop(0), None)
        while len(self._layout_cache) > self._cache_capacity:
            self._layout_cache.popitem(last=False)
        while self.cache_rows > self._cache_line_capacity and len(self._layout_cache) > 1:
            self._layout_cache.popitem(last=False)
        self._layout_index.measure(block, width, rendered, key[2])

    def _render_cached(self, block, width: int) -> list[RichLine]:
        rendered = self._cache_lookup(block, width)
        if rendered is not None:
            return rendered
        rendered = block.render(width)
        self._cache_store(block, width, rendered)
        self.cache_misses += 1
        return rendered

    def _rows(self, width: int, transient=None) -> tuple[list[RichLine], list]:
        """构造完整内容行与点击映射；退出路径允许有界之外的物化。"""
        rows: list[RichLine] = []
        owners: list = []
        cursor = 0
        first = True
        self.layout_index = []
        self._range_starts = []
        for block in self._blocks:
            rendered = self._render_cached(block, width)
            if not rendered:
                continue
            if not first:
                rows.append([])
                owners.append(None)
                cursor += 1
            first = False
            start = cursor
            rows.extend(rendered)
            owners.extend([block] * len(rendered))
            cursor += len(rendered)
            self.layout_index.append((start, cursor, block))
            self._range_starts.append(start)
        if transient is not None:
            rendered = transient.render(width)
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

    def _geometry(self, width: int, height: int, transient_rendered: list[RichLine]):
        persistent_total = self._layout_index.total_rows(width)
        transient_height = max(1, len(transient_rendered)) if transient_rendered else 0
        total = persistent_total
        if transient_height:
            total += (1 if persistent_total else 0) + transient_height
        if not self.follow and self._scroll_top >= max(0, total - height):
            self.follow = True
        anchored = self._restore_anchor_start(width, height, total)
        if anchored is not None:
            start = anchored
        else:
            start = max(0, total - height) if self.follow else min(self._scroll_top, max(0, total - height))
        self._scroll_top = start
        return persistent_total, total, start

    def _collect_visible(
        self,
        width: int,
        height: int,
        persistent_total: int,
        total: int,
        start: int,
        transient_rendered: list[RichLine],
        transient,
    ) -> list[RichLine]:
        visible_end = start + height
        entries = self._layout_index.entries_from(width, start, visible_end)
        visible_pairs: list[tuple[int, RichLine, object | None]] = []
        self.layout_index = []
        self._range_starts = []
        for record, block_start, block_end, has_separator in entries:
            rendered = self._cache_lookup(record.block, width)
            if rendered is None:
                continue
            self.layout_index.append((block_start, block_end, record.block))
            self._range_starts.append(block_start)
            if has_separator:
                separator = block_start - 1
                if start <= separator < visible_end:
                    visible_pairs.append((separator, [], None))
            for index, line in enumerate(rendered, start=block_start):
                if start <= index < visible_end:
                    visible_pairs.append((index, line, record.block))
        if transient is not None and transient_rendered:
            transient_start = persistent_total + (1 if persistent_total else 0)
            separator = transient_start - 1
            if start <= separator < visible_end and persistent_total:
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
        self._capture_anchor(width)
        return visible

    def render(self, width: int, height: int, transient=None) -> list[RichLine]:
        """只物化视口及 overscan 范围内的块，维护行到块映射。"""
        height = max(0, height)
        width = max(1, width)
        if self._last_width != width and not self.follow:
            self._restore_anchor = True
        self._last_width = width
        if not self.follow and len(self._blocks) > self._last_block_count:
            self._new_output_count += len(self._blocks) - self._last_block_count
        transient_rendered = transient.render(width) if transient is not None else []
        self.layout_stats = {"blocks_inspected": 0, "blocks_materialized": 0, "index_updates": 0}
        before_updates = self._layout_index.update_count
        for _ in range(3):
            persistent_total, total, start = self._geometry(width, height, transient_rendered)
            window_start = max(0, start - self.overscan)
            window_end = min(total, start + height + self.overscan)
            entries = self._layout_index.entries_from(width, window_start, window_end)
            self.layout_stats["blocks_inspected"] += len(entries)
            changed = False
            for record, block_start, block_end, _ in entries:
                if block_end <= window_start or block_start >= window_end:
                    continue
                if self._cache_lookup(record.block, width) is None:
                    self._cache_block(record.block, width)
                    self.layout_stats["blocks_materialized"] += 1
                    changed = True
            if not changed:
                break
        persistent_total, total, start = self._geometry(width, height, transient_rendered)
        self._last_total = total
        self.layout_stats["index_updates"] = self._layout_index.update_count - before_updates
        visible = self._collect_visible(
            width, height, persistent_total, total, start, transient_rendered, transient
        )
        self._last_block_count = len(self._blocks)
        if self.follow:
            self._new_output_count = 0
        return visible

    def _cache_block(self, block, width: int) -> list[RichLine]:
        return self._render_cached(block, width)
