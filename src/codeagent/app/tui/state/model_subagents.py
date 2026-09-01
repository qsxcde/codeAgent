"""TUI 对 Subagent 专用事件的有界投影。"""

from __future__ import annotations

from typing import Any

from codeagent.core.contracts.events import AgentEvent, EventType

from ..presentation.blocks import SubagentBlock

_MAX_SUBAGENT_BLOCKS = 64
_ACTIVE_STATUSES = frozenset(
    {"created", "queued", "starting", "running", "waiting_confirmation", "cancelling"}
)


class SubagentEventMixin:
    """把父级 Subagent 事件映射为独立块，不触碰父 runtime。"""

    @property
    def subagent_blocks(self) -> list[SubagentBlock]:
        """Return compact projections in event arrival order."""
        return list(self._subagent_blocks_by_id.values())

    @property
    def subagent_block_capacity(self) -> int:
        return _MAX_SUBAGENT_BLOCKS

    def hydrate_subagent_records(self, records: list[Any]) -> None:
        """Restore compact delegation facts without replaying runtime events."""
        for record in records:
            delegation_id = str(_record_value(record, "delegation_id") or "")
            if not delegation_id or delegation_id in self._subagent_evicted_ids:
                continue
            if delegation_id in self._subagent_blocks_by_id:
                continue
            status = str(_record_value(record, "status") or "abandoned")
            if status in _ACTIVE_STATUSES:
                status = "abandoned"
            metadata = {
                "delegation_id": delegation_id,
                "parent_run_id": str(_record_value(record, "parent_run_id") or ""),
                "child_run_id": _record_value(record, "child_run_id"),
                "attempt_id": _record_value(record, "attempt_id"),
                "profile": str(_record_value(record, "profile") or ""),
                "task_label": str(_record_value(record, "task_label") or ""),
                "subagent_status": status,
                "child_phase": str(_record_value(record, "phase") or status),
                "reason_code": str(_record_value(record, "reason_code") or ""),
                "cleanup_uncertain": bool(_record_value(record, "cleanup_uncertain")),
            }
            payload = dict(_record_value(record, "result") or {})
            payload.setdefault("summary", str(_record_value(record, "summary") or ""))
            diagnostics = list(_record_value(record, "diagnostics") or [])
            if diagnostics:
                payload.setdefault("diagnostics", diagnostics)
            if metadata["reason_code"] and "failure" not in payload:
                payload["failure"] = {"reason_code": metadata["reason_code"]}
            if metadata["cleanup_uncertain"]:
                payload["cleanup_uncertain"] = True
            block = SubagentBlock(
                delegation_id,
                task_label=metadata["task_label"],
                profile=metadata["profile"],
            )
            block.parent_run_id = metadata["parent_run_id"] or None
            self._subagent_blocks_by_id[delegation_id] = block
            self.transcript.append(block)
            block.apply_event(AgentEvent(EventType.SUBAGENT_FINISHED, payload=payload, metadata=metadata))
            self._trim_subagent_blocks()
        self._sync_subagent_counts()

    def _apply_subagent_event(self, event: AgentEvent) -> None:
        metadata = self._subagent_metadata(event)
        parent_run_id = str(metadata.get("parent_run_id") or "")
        current_run_id = str(getattr(self.runtime, "run_id", None) or "")
        if not parent_run_id or not current_run_id or parent_run_id != current_run_id:
            return
        delegation_id = str(metadata.get("delegation_id") or "")
        if not delegation_id or delegation_id in self._subagent_evicted_ids:
            return
        block = self._subagent_blocks_by_id.get(delegation_id)
        if block is None:
            if event.type != EventType.SUBAGENT_QUEUED:
                return
            block = SubagentBlock(
                delegation_id,
                task_label=str(metadata.get("task_label") or ""),
                profile=str(metadata.get("profile") or ""),
            )
            block.parent_run_id = parent_run_id
            self._subagent_blocks_by_id[delegation_id] = block
            self.transcript.append(block)
            self._trim_subagent_blocks()
        if block.apply_event(event):
            self._sync_subagent_counts()

    def _subagent_metadata(self, event: AgentEvent) -> dict[str, Any]:
        metadata = dict(event.metadata or {})
        for name in ("delegation_id", "parent_run_id", "profile", "task_label"):
            value = getattr(event, name, None)
            if value is not None:
                metadata.setdefault(name, value)
        return metadata

    def _sync_subagent_counts(self) -> None:
        current_run_id = str(getattr(self.runtime, "run_id", None) or "")
        counts: dict[str, int] = {}
        for block in self._subagent_blocks_by_id.values():
            if block.parent_run_id != current_run_id or block.status not in _ACTIVE_STATUSES:
                continue
            key = "waiting" if block.status == "waiting_confirmation" else "running"
            counts[key] = counts.get(key, 0) + 1
        failed = sum(
            1
            for block in self._subagent_blocks_by_id.values()
            if block.parent_run_id == current_run_id
            and block.status in {"failed", "timed_out", "rejected"}
        )
        if failed:
            counts["failed"] = failed
        self.status.subagent_counts = counts

    def _trim_subagent_blocks(self) -> None:
        while len(self._subagent_blocks_by_id) > _MAX_SUBAGENT_BLOCKS:
            delegation_id, block = self._subagent_blocks_by_id.popitem(last=False)
            if not block.is_terminal:
                self._subagent_evicted_ids.add(delegation_id)
                if len(self._subagent_evicted_ids) > _MAX_SUBAGENT_BLOCKS:
                    self._subagent_evicted_ids.pop()

    def _reset_subagent_projection(self) -> None:
        self._subagent_blocks_by_id.clear()
        self._subagent_evicted_ids.clear()
        self.status.subagent_counts = {}

    def _cancel_active_subagents(self, event: AgentEvent | None = None) -> None:
        cleanup_uncertain = bool(
            event is not None and (event.metadata or {}).get("cleanup_uncertain")
        )
        for block in self._subagent_blocks_by_id.values():
            if block.status in _ACTIVE_STATUSES:
                block.cancel_from_parent(cleanup_uncertain=cleanup_uncertain)
        self._sync_subagent_counts()


def _record_value(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


__all__ = ["SubagentEventMixin"]
