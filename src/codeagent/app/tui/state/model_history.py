"""TUI 模型的会话历史投影。"""

from __future__ import annotations

from typing import Any

from ..presentation.blocks import AssistantBlock, ToolCallBlock, UserBlock
from ..presentation.primitives import _visible_user_content


class ModelHistoryMixin:
    """把持久化消息转换成当前模型的可见块。"""

    def hydrate_history(self, history: list[Any], summary: str | None = None) -> None:
        """从会话快照重建 transcript，不写回会话，也不触发模型调用。"""
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
            elif role == "assistant":
                self._restore_assistant_message(message, content)
            elif role == "tool":
                self._restore_tool_result(message, content)

        self.transcript.scroll_to_bottom()

    def _restore_assistant_message(self, message: Any, content: str) -> None:
        if content:
            block = AssistantBlock(clock=self._clock)
            block.append_text(content)
            self.transcript.append(block)
        self._assistant = None
        for call in getattr(message, "tool_calls", None) or []:
            name, args, call_id = self._tool_call_fields(call)
            block = ToolCallBlock(name, args, call_id=call_id)
            self.transcript.append(block)
            self._pending_tools.append(block)
            if block.call_id:
                self._pending_tools_by_id[block.call_id] = block

    @staticmethod
    def _tool_call_fields(call: Any) -> tuple[str, dict[str, Any], str | None]:
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
        return name, args, str(call_id) if call_id else None

    def _restore_tool_result(self, message: Any, content: str) -> None:
        call_id = str(getattr(message, "tool_call_id", "") or "")
        block = self._pending_tools_by_id.pop(call_id, None) if call_id else None
        if block is None and self._pending_tools:
            block = self._pending_tools[0]
            if block.call_id:
                self._pending_tools_by_id.pop(block.call_id, None)
        if block is not None:
            self._pending_tools.remove(block)
            block.set_result(content, execution_status="ok")
