"""TUI 模型的事件到显示块投影。"""

from __future__ import annotations

from ..presentation.blocks import ErrorBlock, UserBlock
from ..presentation.primitives import _visible_user_content
from .runtime import RuntimePhase
from codeagent.core.contracts.events import SUBAGENT_EVENT_TYPES, AgentEvent, EventType
from .model_tools import ToolEventMixin
from .model_subagents import SubagentEventMixin


def _token_label(value: object) -> str:
    """Format optional token metadata for compact TUI diagnostics."""
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


class ModelEventMixin(SubagentEventMixin, ToolEventMixin):
    """维护运行态、活动提示、工具块和助手块。"""

    def apply(self, event: AgentEvent) -> None:
        self._event_count += 1
        if event.type in SUBAGENT_EVENT_TYPES:
            self._apply_subagent_event(event)
            return
        self.runtime = self._runtime_reducer.apply(self.runtime, event)
        self.status.apply_snapshot(self.runtime, now=self._clock())
        self._sync_subagent_counts()
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
            EventType.TOOL_QUEUED: self._apply_tool_lifecycle,
            EventType.TOOL_STARTED: self._apply_tool_lifecycle,
            EventType.TOOL_PROGRESS: self._apply_tool_lifecycle,
            EventType.TOOL_FINISHED: self._apply_tool_lifecycle,
            EventType.TOOL_RESULT: self._apply_tool_result,
            EventType.CONFIRMATION_REQUESTED: self._apply_confirmation,
            EventType.COMPACTION_FINISHED: self._apply_compaction_finished,
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
        self._tool_blocks_by_id.clear()
        self._result_event_ids.clear()
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

    def _apply_compaction_finished(self, event: AgentEvent) -> None:
        metadata = event.metadata or {}
        if metadata.get("trigger") != "auto":
            return
        status = str(metadata.get("status") or "failed")
        reason = str(metadata.get("reason_code") or metadata.get("error_code") or "")
        if status == "compacted":
            self.append_info(
                "自动压缩完成:"
                f"{_token_label(metadata.get('before_input_tokens'))} → "
                f"{_token_label(metadata.get('after_input_tokens'))} token,"
                f"目标 {_token_label(metadata.get('target_budget'))};"
                f"摘要 {metadata.get('summarized_turns', 0)} 轮,"
                f"保留 {metadata.get('kept_turns', 0)} 轮"
            )
        elif status == "skipped":
            self.append_info(f"自动压缩跳过:{reason or '无需压缩'}")
        elif status == "cancelled":
            self.append_info("自动压缩已取消")
        elif status == "persistence_uncertain":
            self.append_info("自动压缩持久化结果不确定")
        else:
            self.append_info(f"自动压缩失败:{reason or '未知原因'}")

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
