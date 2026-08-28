"""TUI 模型的事件到显示块投影。"""

from __future__ import annotations

from ..presentation.blocks import ErrorBlock, ToolCallBlock, UserBlock, CancelledBlock
from ..presentation.primitives import _visible_user_content
from .runtime import RuntimePhase
from codeagent.core.events import AgentEvent, EventType


class ModelEventMixin:
    """维护运行态、活动提示、工具块和助手块。"""

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
        handler = {
            EventType.SESSION_STARTED: self._apply_session_started,
            EventType.THINKING_DELTA: self._apply_thinking,
            EventType.TEXT_DELTA: self._apply_text,
            EventType.AGENT_MESSAGE: self._apply_agent_message,
            EventType.TOOL_CALL: self._apply_tool_call,
            EventType.TOOL_RESULT: self._apply_tool_result,
            EventType.CONFIRMATION_REQUESTED: self._apply_confirmation,
            EventType.TURN_END: self._apply_turn_end,
            EventType.ERROR: self._apply_error,
            EventType.RUN_CANCELLED: self._apply_cancelled,
        }.get(event.type)
        if handler is not None:
            handler(event)

    def _apply_session_started(self, event: AgentEvent) -> None:
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

    def _apply_thinking(self, event: AgentEvent) -> None:
        self._ensure_assistant().append_thinking(str(event.payload or ""))
        self.activity_visible = True

    def _apply_text(self, event: AgentEvent) -> None:
        self._ensure_assistant().append_text(str(event.payload or ""))
        self.activity_visible = False

    def _apply_agent_message(self, event: AgentEvent) -> None:
        assistant = self._ensure_assistant()
        if not assistant.body:
            assistant.append_text(str(event.payload or ""))
        self.activity_visible = False

    def _apply_tool_call(self, event: AgentEvent) -> None:
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

    def _apply_tool_result(self, event: AgentEvent) -> None:
        metadata = event.metadata or {}
        payload_text = str(event.payload or "")
        self.output_stats["results"] += 1
        self.output_stats["bytes"] += int(
            metadata.get("total_bytes") or len(payload_text.encode("utf-8"))
        )
        self.output_stats["lines"] += int(metadata.get("total_lines") or len(payload_text.splitlines()))
        if metadata.get("truncated_by"):
            self.output_stats["truncated"] += 1
        block = self._take_pending_tool(metadata.get("tool_call_id"))
        if block is not None:
            if metadata.get("rejected"):
                block.set_rejected(payload_text)
            else:
                block.set_result(
                    payload_text,
                    error=bool(metadata.get("error")),
                    execution_status=str(metadata.get("status") or ""),
                    output_metadata=metadata,
                )
        if not self._pending_tools:
            self.activity_visible = True

    def _take_pending_tool(self, call_id: object) -> ToolCallBlock | None:
        block = self._pending_tools_by_id.pop(str(call_id), None) if call_id else None
        if block is not None:
            if block in self._pending_tools:
                self._pending_tools.remove(block)
            return block
        if not self._pending_tools:
            return None
        block = self._pending_tools.pop(0)
        if block.call_id:
            self._pending_tools_by_id.pop(block.call_id, None)
        return block

    def _apply_confirmation(self, event: AgentEvent) -> None:
        payload = event.payload or {}
        call_id = str(payload.get("tool_call_id") or "")
        block = self._pending_tools_by_id.get(call_id)
        if block is None and self._pending_tools:
            block = self._pending_tools[0]
        if block is not None:
            block.set_awaiting()
        self.activity_visible = False

    def _apply_turn_end(self, event: AgentEvent) -> None:
        if self._assistant is not None:
            self._assistant.finalize()
        self.running = False
        self._assistant = None
        self.activity_visible = False

    def _apply_error(self, event: AgentEvent) -> None:
        self.transcript.append(ErrorBlock(str(event.payload or "发生错误")))
        self.running = False
        self.activity_visible = False

    def _apply_cancelled(self, event: AgentEvent) -> None:
        self.transcript.append(CancelledBlock())
        self.running = False
        self.activity_visible = False
