"""TUI 事件投影模型：把 AgentEvent 映射为消息块、运行态与统计。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from codeagent.app.tui.blocks import (
    ActivityBlock, AssistantBlock, CancelledBlock, ErrorBlock, ToolCallBlock, UserBlock,
)
from codeagent.app.tui.primitives import RichLine, _visible_user_content
from codeagent.app.tui.runtime import RuntimePhase, RuntimeReducer, RuntimeSnapshot
from codeagent.app.tui.status import StatusBar
from codeagent.app.tui.transcript import Transcript
from codeagent.core.events import AgentEvent, EventType


class TuiModel:
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

    def hydrate_history(self, history: list[Any], summary: str | None = None) -> None:
        """从会话快照重建 transcript,用于切换/恢复持久化会话。

        ``AgentSession`` 的历史是消息模型,而 TUI 运行时状态来自事件流。
        切换会话不会重新发出过去的事件,因此这里按消息顺序重建同一组可见块,
        并将尚未有结果的工具调用保留为 pending。该方法只负责显示历史,
        不会把任何消息重新写回会话或触发模型调用。
        """
        self.transcript.clear()
        self.running = False
        self._assistant = None
        self._pending_tools.clear()
        self._pending_tools_by_id.clear()
        self._pending_user_prompts.clear()
        self.activity_visible = False
        self.activity_frame = 0

        if summary:
            self.append_info(f"上下文摘要\n{summary}")

        for message in history:
            role = str(getattr(message, "role", ""))
            content = str(getattr(message, "content", "") or "")
            if role == "user":
                self.transcript.append(UserBlock(_visible_user_content(content)))
                self._assistant = None
                continue

            if role == "assistant":
                if content:
                    block = AssistantBlock(clock=self._clock)
                    block.append_text(content)
                    self.transcript.append(block)
                self._assistant = None
                for call in getattr(message, "tool_calls", None) or []:
                    if isinstance(call, dict):
                        name = str(call.get("name") or "?")
                        args = call.get("args") or {}
                        call_id = call.get("id")
                    else:
                        name = str(getattr(call, "name", "?") or "?")
                        args = getattr(call, "args", {}) or {}
                        call_id = getattr(call, "id", None)
                    if not isinstance(args, dict):
                        args = {}
                    block = ToolCallBlock(
                        name,
                        args,
                        call_id=str(call_id) if call_id else None,
                    )
                    self.transcript.append(block)
                    self._pending_tools.append(block)
                    if block.call_id:
                        self._pending_tools_by_id[block.call_id] = block
                continue

            if role == "tool":
                call_id = str(getattr(message, "tool_call_id", "") or "")
                block = self._pending_tools_by_id.pop(call_id, None) if call_id else None
                if block is None and self._pending_tools:
                    block = self._pending_tools[0]
                    if block.call_id:
                        self._pending_tools_by_id.pop(block.call_id, None)
                if block is not None:
                    self._pending_tools.remove(block)
                    block.set_result(content, execution_status="ok")

        self.transcript.scroll_to_bottom()

    def apply(self, event: AgentEvent) -> None:
        self._event_count += 1
        self.runtime = self._runtime_reducer.apply(self.runtime, event)
        self.status.apply_snapshot(self.runtime, now=self._clock())
        self.running = self.runtime.phase in {
            RuntimePhase.WAITING_MODEL,
            RuntimePhase.STREAMING,
            RuntimePhase.TOOL_RUNNING,
            RuntimePhase.AWAITING_CONFIRMATION,
            RuntimePhase.COMPACTING,
            RuntimePhase.CANCELLING,
            RuntimePhase.RESTORING,
        }
        ev_type = event.type
        if ev_type == EventType.SESSION_STARTED:
            content = _visible_user_content(str(event.payload))
            if content in self._pending_user_prompts:
                self._pending_user_prompts.remove(content)
            else:
                self.transcript.append(UserBlock(content))
            self._assistant = None
            self._pending_tools.clear()
            self._pending_tools_by_id.clear()
            self.running = True
            self.activity_visible = True
            self.activity_frame = 0
        elif ev_type == EventType.THINKING_DELTA:
            self._ensure_assistant().append_thinking(str(event.payload or ""))
            self.activity_visible = True
        elif ev_type == EventType.TEXT_DELTA:
            self._ensure_assistant().append_text(str(event.payload or ""))
            self.activity_visible = False
        elif ev_type == EventType.AGENT_MESSAGE:
            assistant = self._ensure_assistant()
            if not assistant.body:
                assistant.append_text(str(event.payload or ""))
            self.activity_visible = False
        elif ev_type == EventType.TOOL_CALL:
            for call in event.payload or []:
                name = call.get("name", "?") if isinstance(call, dict) else "?"
                args = call.get("args", {}) if isinstance(call, dict) else {}
                if not isinstance(args, dict):
                    args = {}
                call_id = str(call.get("id")) if isinstance(call, dict) and call.get("id") else None
                block = ToolCallBlock(name, args, call_id=call_id)
                self.transcript.append(block)
                self._pending_tools.append(block)
                if call_id:
                    self._pending_tools_by_id[call_id] = block
            self.activity_visible = False
            self._assistant = None
        elif ev_type == EventType.TOOL_RESULT:
            metadata = event.metadata or {}
            self.output_stats["results"] += 1
            self.output_stats["bytes"] += int(metadata.get("total_bytes") or len(str(event.payload or "").encode("utf-8")))
            self.output_stats["lines"] += int(metadata.get("total_lines") or len(str(event.payload or "").splitlines()))
            if metadata.get("truncated_by"):
                self.output_stats["truncated"] += 1
            call_id = metadata.get("tool_call_id")
            block = self._pending_tools_by_id.pop(str(call_id), None) if call_id else None
            if block is not None:
                if block in self._pending_tools:
                    self._pending_tools.remove(block)
            elif self._pending_tools:
                block = self._pending_tools.pop(0)
                if block.call_id:
                    self._pending_tools_by_id.pop(block.call_id, None)
            if block is not None:
                if metadata.get("rejected"):
                    block.set_rejected(str(event.payload or ""))
                else:
                    block.set_result(
                        str(event.payload or ""),
                        error=bool(metadata.get("error")),
                        execution_status=str(metadata.get("status") or ""),
                        output_metadata=metadata,
                    )
            if not self._pending_tools:
                self.activity_visible = True
        elif ev_type == EventType.CONFIRMATION_REQUESTED:
            # 确认请求:标记对应工具块为等待确认(security-permissions)。
            payload = event.payload or {}
            call_id = str(payload.get("tool_call_id") or "")
            block = self._pending_tools_by_id.get(call_id)
            if block is None and self._pending_tools:
                block = self._pending_tools[0]
            if block is not None:
                block.set_awaiting()
            self.activity_visible = False
        elif ev_type == EventType.TURN_END:
            if self._assistant is not None:
                self._assistant.finalize()
            self.running = False
            self._assistant = None
            self.activity_visible = False
        elif ev_type == EventType.ERROR:
            self.transcript.append(ErrorBlock(str(event.payload or "发生错误")))
            self.running = False
            self.activity_visible = False
        elif ev_type == EventType.RUN_CANCELLED:
            self.transcript.append(CancelledBlock())
            self.running = False
            self.activity_visible = False
