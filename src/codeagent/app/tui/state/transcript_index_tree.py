"""Transcript width-specific chunk records and prefix lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from ..presentation.primitives import Component

_CHUNK_SIZE = 64


@dataclass
class LayoutRecord:
    """One block's width-specific layout facts."""

    token: int
    block: Component
    revision: int
    height: int
    visible: bool
    exact: bool = False

    @property
    def contribution(self) -> int:
        """Return content rows plus a trailing separator when visible."""
        return self.height + 1 if self.visible else 0


class _PrefixTree:
    """Small dynamic segment tree over chunk totals."""

    def __init__(self) -> None:
        self._size = 1
        self._tree = [0, 0]

    def rebuild(self, values: list[int]) -> None:
        size = 1
        while size < max(1, len(values)):
            size <<= 1
        self._size = size
        self._tree = [0] * (size * 2)
        for index, value in enumerate(values):
            self._tree[size + index] = value
        for index in range(size - 1, 0, -1):
            self._tree[index] = self._tree[index * 2] + self._tree[index * 2 + 1]

    def update(self, index: int, value: int) -> None:
        position = self._size + index
        delta = value - self._tree[position]
        self._tree[position] = value
        position //= 2
        while position:
            self._tree[position] += delta
            position //= 2

    def total(self) -> int:
        return self._tree[1]

    def prefix_sum(self, end: int) -> int:
        """Return the sum of values before ``end``."""
        result = 0
        left = self._size
        right = self._size + end
        while left < right:
            if left & 1:
                result += self._tree[left]
                left += 1
            if right & 1:
                right -= 1
                result += self._tree[right]
            left //= 2
            right //= 2
        return result

    def locate(self, target: int) -> int:
        """Locate the first leaf whose cumulative sum is at least target."""
        if target <= 0 or target > self.total():
            raise IndexError("prefix target outside index")
        node = 1
        while node < self._size:
            left = node * 2
            if self._tree[left] >= target:
                node = left
            else:
                target -= self._tree[left]
                node = left + 1
        return node - self._size


class WidthLayout:
    """Width-specific records and a chunk prefix index."""

    def __init__(self, blocks: list[tuple[int, Component]]) -> None:
        self.records: list[LayoutRecord] = [self._estimate(token, block) for token, block in blocks]
        self.chunks: list[list[LayoutRecord]] = []
        self.positions: dict[int, tuple[int, int]] = {}
        self.tree = _PrefixTree()
        self._rebuild()

    @staticmethod
    def _estimate(token: int, block: Component) -> LayoutRecord:
        visible = bool(getattr(block, "has_body", True))
        return LayoutRecord(
            token=token,
            block=block,
            revision=int(getattr(block, "revision", 0)),
            height=1 if visible else 0,
            visible=visible,
        )

    def _rebuild(self) -> None:
        self.chunks = [
            self.records[start : start + _CHUNK_SIZE]
            for start in range(0, len(self.records), _CHUNK_SIZE)
        ]
        self.positions = {}
        totals: list[int] = []
        for chunk_index, chunk in enumerate(self.chunks):
            total = 0
            for offset, record in enumerate(chunk):
                self.positions[record.token] = (chunk_index, offset)
                total += record.contribution
            totals.append(total)
        self.tree.rebuild(totals)

    def _refresh_chunk(self, chunk_index: int) -> None:
        self.tree.update(
            chunk_index,
            sum(record.contribution for record in self.chunks[chunk_index]),
        )

    def add(self, record: LayoutRecord) -> None:
        self.records.append(record)
        if not self.chunks or len(self.chunks[-1]) >= _CHUNK_SIZE:
            self._rebuild()
            return
        chunk_index = len(self.chunks) - 1
        offset = len(self.chunks[-1])
        self.chunks[-1].append(record)
        self.positions[record.token] = (chunk_index, offset)
        self._refresh_chunk(chunk_index)

    def remove(self, token: int) -> None:
        chunk_index, offset = self.positions[token]
        self.records.pop(chunk_index * _CHUNK_SIZE + offset)
        self._rebuild()

    def record(self, token: int) -> LayoutRecord:
        chunk_index, offset = self.positions[token]
        return self.chunks[chunk_index][offset]

    def update(self, record: LayoutRecord, *, height: int, visible: bool, exact: bool) -> bool:
        changed = record.height != height or record.visible != visible or record.exact != exact
        record.height = max(0, int(height))
        record.visible = bool(visible)
        record.exact = exact
        if changed:
            self._refresh_chunk(self.positions[record.token][0])
        return changed

    def raw_prefix_before(self, chunk_index: int, offset: int) -> int:
        return self.tree.prefix_sum(chunk_index) + sum(
            record.contribution for record in self.chunks[chunk_index][:offset]
        )

    def total_rows(self) -> int:
        raw_total = self.tree.total()
        return max(0, raw_total - 1) if raw_total else 0

    def _start_position(self, row: int) -> tuple[int, int, int] | None:
        if row < 0 or row >= self.total_rows():
            return None
        target = row + 1
        chunk_index = self.tree.locate(target)
        chunk = self.chunks[chunk_index]
        before = self.tree.prefix_sum(chunk_index)
        for offset, record in enumerate(chunk):
            contribution = record.contribution
            if contribution and before + contribution >= target:
                return chunk_index, offset, before
            before += contribution
        return None

    def entries_from(self, row: int, end: int) -> Iterator[tuple[LayoutRecord, int, int, bool]]:
        """Yield visible records intersecting ``[row, end)``."""
        position = self._start_position(row)
        if position is None:
            return
        chunk_index, offset, raw_before = position
        while chunk_index < len(self.chunks):
            chunk = self.chunks[chunk_index]
            while offset < len(chunk):
                record = chunk[offset]
                if record.visible:
                    block_start = raw_before
                    block_end = block_start + record.height
                    separator = block_start - 1
                    intersects = block_end > row and block_start < end
                    separator_intersects = raw_before > 0 and row <= separator < end
                    if intersects or separator_intersects:
                        yield record, block_start, block_end, raw_before > 0
                    if block_start >= end:
                        return
                raw_before += record.contribution
                offset += 1
            chunk_index += 1
            offset = 0

    def block_at(self, row: int) -> tuple[Component, int] | None:
        """Map an absolute content row to a block and local row."""
        position = self._start_position(row)
        if position is None:
            return None
        chunk_index, offset, raw_before = position
        record = self.chunks[chunk_index][offset]
        local = row - raw_before
        if 0 <= local < record.height:
            return record.block, local
        return None

    def position(self, token: int) -> tuple[int, int, int] | None:
        """Return ``(block_start, height, revision)`` for an indexed token."""
        location = self.positions.get(token)
        if location is None:
            return None
        chunk_index, offset = location
        record = self.chunks[chunk_index][offset]
        return self.raw_prefix_before(chunk_index, offset), record.height, record.revision
