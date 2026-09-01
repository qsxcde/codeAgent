"""TUI 工具事件到工具块的按调用 ID 投影。"""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.tool_status import ToolLifecycleStatus

from ..presentation.blocks import CancelledBlock, ToolCallBlock
from .tool_lifecycle import is_terminal, normalize_status


class ToolEventMixin:
    """维护工具块、活动工具集合和结果统计。"""

    def _apply_tool_call(self, event: AgentEvent) -> None:
        for call in event.payload or []:
            name = call.get("name", "?") if isinstance(call, dict) else "?"
            args = call.get("args", {}) if isinstance(call, dict) else {}
            if not isinstance(args, dict):
                args = {}
            call_id = str(call.get("id")) if isinstance(call, dict) and call.get("id") else None
            block = self._get_or_create_tool_block(call_id, str(name), args)
            block.set_queued()
            self._track_pending(block)
        self.activity_visible = False
        self._assistant = None

    def _apply_tool_lifecycle(self, event: AgentEvent) -> None:
        metadata = self._event_metadata(event)
        call_id = str(metadata.get("tool_call_id") or "")
        payload = event.payload if isinstance(event.payload, dict) else {}
        name = str(metadata.get("tool_name") or payload.get("name") or "?")
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        block = self._get_or_create_tool_block(call_id or None, name, args)
        default_status = {
            EventType.TOOL_QUEUED: ToolLifecycleStatus.QUEUED,
            EventType.TOOL_STARTED: ToolLifecycleStatus.RUNNING,
            EventType.TOOL_PROGRESS: ToolLifecycleStatus.RUNNING,
            EventType.TOOL_FINISHED: ToolLifecycleStatus.COMPLETED,
        }[event.type]
        status = normalize_status(metadata.get("status"), default_status)
        progress_text = event.payload if isinstance(event.payload, str) else None
        block.set_execution_status(
            status,
            cleanup_status=metadata.get("cleanup_status"),
            cleanup_uncertain=bool(metadata.get("cleanup_uncertain")),
            elapsed_ms=_int_or_none(metadata.get("elapsed_ms")),
            queue_position=_int_or_none(metadata.get("queue_position")),
            error_code=metadata.get("error_code"),
            progress_text=progress_text,
        )
        if is_terminal(block.execution_status):
            self._remove_pending_tool(block)
        else:
            self._track_pending(block)
        self.activity_visible = not self._pending_tools

    def _apply_tool_result(self, event: AgentEvent) -> None:
        metadata = self._event_metadata(event)
        payload_text = str(event.payload or "")
        call_id = str(metadata.get("tool_call_id") or "")
        if not call_id or call_id not in self._result_event_ids:
            if call_id:
                self._result_event_ids.add(call_id)
            self.output_stats["results"] += 1
            self.output_stats["bytes"] += _int_or_default(
                metadata.get("total_bytes"), len(payload_text.encode("utf-8"))
            )
            self.output_stats["lines"] += _int_or_default(
                metadata.get("total_lines"), len(payload_text.splitlines())
            )
            if metadata.get("truncated_by") or metadata.get("completeness") in {
                "truncated",
                "incomplete",
                "unsupported",
            }:
                self.output_stats["truncated"] += 1
        block = self._take_pending_tool(metadata.get("tool_call_id"))
        if block is None:
            name = str(metadata.get("tool_name") or "?")
            block = self._get_or_create_tool_block(call_id or None, name, {})
        if metadata.get("rejected"):
            block.set_rejected(payload_text)
        else:
            block.set_result(
                payload_text,
                error=bool(metadata.get("error")),
                execution_status=(str(metadata["status"]) if metadata.get("status") else None),
                output_metadata=metadata,
                cleanup_status=metadata.get("cleanup_status"),
                cleanup_uncertain=bool(metadata.get("cleanup_uncertain")),
                elapsed_ms=_int_or_none(metadata.get("elapsed_ms")),
                error_code=metadata.get("error_code"),
            )
        self._remove_pending_tool(block)
        if not self._pending_tools:
            self.activity_visible = True

    def _event_metadata(self, event: AgentEvent) -> dict[str, object]:
        metadata = dict(event.metadata or {})
        for field_name in (
            "session_id",
            "run_id",
            "tool_call_id",
            "operation_id",
            "elapsed_ms",
            "error_code",
            "cleanup_uncertain",
            "cleanup_status",
            "status",
            "tool_name",
            "queue_position",
        ):
            value = getattr(event, field_name, None)
            if value is not None:
                metadata.setdefault(field_name, value)
        return metadata

    def _get_or_create_tool_block(
        self,
        call_id: str | None,
        name: str,
        args: dict[str, object],
    ) -> ToolCallBlock:
        block = self._tool_blocks_by_id.get(call_id) if call_id else None
        if block is not None:
            if block.name == "?" and name != "?":
                block.name = name
            if not block.args and args:
                block.args = args
            return block
        block = ToolCallBlock(name, args, call_id=call_id)
        self.transcript.append(block)
        if call_id:
            self._tool_blocks_by_id[call_id] = block
        return block

    def _track_pending(self, block: ToolCallBlock) -> None:
        if block not in self._pending_tools:
            self._pending_tools.append(block)
        if block.call_id:
            self._pending_tools_by_id[block.call_id] = block

    def _remove_pending_tool(self, block: ToolCallBlock) -> None:
        if block in self._pending_tools:
            self._pending_tools.remove(block)
        if block.call_id and self._pending_tools_by_id.get(block.call_id) is block:
            self._pending_tools_by_id.pop(block.call_id, None)

    def _take_pending_tool(self, call_id: object) -> ToolCallBlock | None:
        block = self._pending_tools_by_id.get(str(call_id)) if call_id else None
        if block is not None:
            self._remove_pending_tool(block)
            return block
        if call_id:
            return None
        if not self._pending_tools:
            return None
        block = self._pending_tools.pop(0)
        if block.call_id:
            self._pending_tools_by_id.pop(block.call_id, None)
        return block

    def _apply_confirmation(self, event: AgentEvent) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        metadata = self._event_metadata(event)
        call_id = str(payload.get("tool_call_id") or metadata.get("tool_call_id") or "")
        block = self._pending_tools_by_id.get(call_id) if call_id else None
        if block is None and not call_id and self._pending_tools:
            block = self._pending_tools[0]
        if block is None and call_id:
            block = self._get_or_create_tool_block(
                call_id,
                str(payload.get("tool") or metadata.get("tool_name") or "?"),
                {},
            )
        if block is not None:
            block.set_awaiting()
            self._track_pending(block)
        self.activity_visible = False

    def _apply_cancelled(self, event: AgentEvent) -> None:
        cancel_subagents = getattr(self, "_cancel_active_subagents", None)
        if callable(cancel_subagents):
            cancel_subagents(event)
        metadata = self._event_metadata(event)
        target_id = str(metadata.get("tool_call_id") or "")
        blocks = list(self._pending_tools)
        if target_id:
            blocks = [
                block
                for block in self.transcript.blocks
                if isinstance(block, ToolCallBlock) and block.call_id == target_id
            ]
        for block in blocks:
            if block.execution_status in {
                ToolLifecycleStatus.QUEUED,
                ToolLifecycleStatus.RUNNING,
                ToolLifecycleStatus.AWAITING_CONFIRMATION,
            }:
                block.set_cancelled(
                    cleanup_status=metadata.get("cleanup_status"),
                    cleanup_uncertain=bool(metadata.get("cleanup_uncertain")),
                    elapsed_ms=_int_or_none(metadata.get("elapsed_ms")),
                )
            self._remove_pending_tool(block)
        self.transcript.append(CancelledBlock())
        self.running = False
        self.activity_visible = False


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: object, default: int) -> int:
    converted = _int_or_none(value)
    return default if converted is None else converted
