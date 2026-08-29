"""Transcript 的增量布局索引。"""

from __future__ import annotations

from collections import OrderedDict

from ..presentation.primitives import Component, RichLine
from .transcript_index_tree import LayoutRecord, WidthLayout


class TranscriptLayoutIndex:
    """Maintain block heights incrementally while bounding per-frame traversal."""

    def __init__(self, *, max_width_variants: int = 3) -> None:
        self._next_token = 1
        self._blocks: list[tuple[int, Component]] = []
        self._tokens: dict[int, int] = {}
        self._states: OrderedDict[int, WidthLayout] = OrderedDict()
        self._max_width_variants = max(1, int(max_width_variants))
        self.update_count = 0

    @staticmethod
    def _is_visible(block: Component) -> bool:
        return bool(getattr(block, "has_body", True))

    def register(self, block: Component) -> int:
        token = self._next_token
        self._next_token += 1
        self._blocks.append((token, block))
        self._tokens[id(block)] = token
        for state in self._states.values():
            state.add(state._estimate(token, block))
        return token

    def unregister(self, block: Component) -> None:
        token = self._tokens.pop(id(block))
        self._blocks = [
            (item_token, item) for item_token, item in self._blocks if item_token != token
        ]
        for state in self._states.values():
            state.remove(token)
        self.update_count += 1

    def clear(self) -> None:
        self._blocks.clear()
        self._tokens.clear()
        self._states.clear()

    def token_for(self, block: Component) -> int | None:
        return self._tokens.get(id(block))

    def _state(self, width: int) -> WidthLayout:
        width = max(1, int(width))
        state = self._states.pop(width, None)
        if state is None:
            state = WidthLayout(self._blocks)
        self._states[width] = state
        while len(self._states) > self._max_width_variants:
            self._states.popitem(last=False)
        return state

    def total_rows(self, width: int) -> int:
        return self._state(width).total_rows()

    def entries_from(
        self, width: int, row: int, end: int
    ) -> list[tuple[LayoutRecord, int, int, bool]]:
        return list(self._state(width).entries_from(row, end))

    def block_at(self, width: int, row: int) -> tuple[Component, int] | None:
        return self._state(width).block_at(row)

    def position(self, width: int, token: int) -> tuple[int, int, int] | None:
        return self._state(width).position(token)

    def invalidate(self, block: Component) -> None:
        token = self.token_for(block)
        if token is None:
            return
        visible = self._is_visible(block)
        revision = int(getattr(block, "revision", 0))
        for state in self._states.values():
            record = state.record(token)
            height = (record.height or 1) if visible else 0
            state.update(record, height=height, visible=visible, exact=False)
            record.revision = revision
        self.update_count += 1

    def measure(
        self, block: Component, width: int, rendered: list[RichLine], revision: int
    ) -> bool:
        token = self.token_for(block)
        if token is None or revision != int(getattr(block, "revision", 0)):
            return False
        state = self._state(width)
        record = state.record(token)
        changed = state.update(
            record,
            height=len(rendered),
            visible=bool(rendered),
            exact=True,
        )
        record.revision = revision
        if changed:
            self.update_count += 1
        return changed
