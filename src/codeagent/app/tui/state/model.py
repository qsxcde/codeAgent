"""TUI 事件投影模型：把 AgentEvent 映射为消息块、运行态与统计。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..presentation.blocks import (
    ActivityBlock, AssistantBlock, CancelledBlock, ErrorBlock, ToolCallBlock, UserBlock,
)
from .model_events import ModelEventMixin
from .model_history import ModelHistoryMixin
from ..presentation.primitives import RichLine, _visible_user_content
from .runtime import RuntimePhase, RuntimeReducer, RuntimeSnapshot
from ..presentation.status import StatusBar
from .transcript import Transcript
from codeagent.core.events import AgentEvent


class TuiModel(ModelHistoryMixin, ModelEventMixin):
    """「事件 → 组件状态」的纯映射(design D3)。

    ``clock`` 可注入(默认 ``time.monotonic``):思考耗时测量依赖它,
    离线测试注入假时钟保持「给定事件序列 → 渲染行」的纯函数性质。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.transcript = Transcript()
        self.status = StatusBar()
        self.running = False
        self._clock = clock
        self._assistant: AssistantBlock | None = None
        self._pending_tools: list[ToolCallBlock] = []
        self._pending_tools_by_id: dict[str, ToolCallBlock] = {}
        self._pending_user_prompts: list[str] = []
        self.activity_visible = False
        self.activity_frame = 0
        self.runtime = RuntimeSnapshot()
        self._runtime_reducer = RuntimeReducer(clock=clock)
        self.render_stats: dict[str, int | float] = {
            "frames": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "last_render_ms": 0.0,
        }
        self.output_stats: dict[str, int] = {
            "results": 0,
            "truncated": 0,
            "bytes": 0,
            "lines": 0,
        }
        self._event_count = 0

    def render(self, width: int, height: int) -> list[RichLine]:
        started = self._clock()
        transient = ActivityBlock(self.activity_frame) if self.activity_visible else None
        lines = self.transcript.render(width, height, transient=transient)
        self.status.new_output_count = self.transcript.new_output_count
        self.render_stats["cache_hits"] = self.transcript.cache_hits
        self.render_stats["cache_misses"] = self.transcript.cache_misses
        self.render_stats["frames"] = int(self.render_stats["frames"]) + 1
        self.render_stats["last_render_ms"] = round((self._clock() - started) * 1000, 3)
        return lines

    def advance_activity(self) -> None:
        if self.activity_visible:
            self.activity_frame += 1

    def performance_snapshot(self) -> dict[str, int | float]:
        """Return content-free counters for offline performance measurements."""
        start, end = self.transcript.visible_range
        return {
            "event_count": self._event_count,
            "block_count": len(self.transcript.blocks),
            "visible_rows": max(0, end - start),
            "visible_start": start,
            "visible_end": end,
            "cache_entries": self.transcript.cache_entries,
            "cache_hits": self.transcript.cache_hits,
            "cache_misses": self.transcript.cache_misses,
            "frames": int(self.render_stats["frames"]),
        }

    def set_context_status(
        self,
        tokens: int | None,
        window: int | None,
        *,
        stale: bool = False,
    ) -> None:
        """同步组合根/会话层提供的上下文窗口信息。"""
        self.runtime = replace(
            self.runtime,
            context_tokens=tokens,
            context_window=window,
            context_stale=stale,
        )
        self.status.apply_snapshot(self.runtime, now=self._clock())

    def _ensure_assistant(self) -> AssistantBlock:
        if self._assistant is None:
            self._assistant = AssistantBlock(clock=self._clock)
            self.transcript.append(self._assistant)
        return self._assistant

    def append_info(self, text: str) -> None:
        """追加一条命令输出块(纯 TUI 显示,不进入会话历史,不改运行态)。"""
        block = AssistantBlock(clock=self._clock)
        block.append_text(text)
        self.transcript.append(block)

    def append_pending_user(self, text: str) -> None:
        """立即显示待启动会话的用户消息，并等待启动事件去重。"""
        content = _visible_user_content(text)
        self.transcript.append(UserBlock(content))
        self._pending_user_prompts.append(content)

    def page_output(self, delta: int, call_id: str | None = None) -> bool:
        """切换工具输出页，只改变视图游标。"""
        candidates = [
            block
            for block in self.transcript.blocks
            if isinstance(block, ToolCallBlock) and block.output_buffer is not None
        ]
        if call_id:
            candidates = [block for block in candidates if block.call_id == call_id]
        if not candidates:
            return False
        block = candidates[-1]
        changed = block.output_buffer.next_page() if delta > 0 else block.output_buffer.previous_page()
        if changed:
            block.touch()
        return changed

    def export_output(self, path: str, call_id: str | None = None) -> str:
        """显式导出工具原始输出，返回可定位路径。"""
        candidates = [
            block
            for block in self.transcript.blocks
            if isinstance(block, ToolCallBlock) and block.output_buffer is not None
        ]
        if call_id:
            candidates = [block for block in candidates if block.call_id == call_id]
        if not candidates:
            raise ValueError("没有可导出的工具输出")
        return str(candidates[-1].output_buffer.export(path))
