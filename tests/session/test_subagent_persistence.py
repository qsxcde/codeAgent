"""父级 Subagent 事件到持久化记录的集成回归。"""

from __future__ import annotations

import json

import pytest

from codeagent.core.contracts.events import AgentEvent, EventType


def _event(event_type: str, *, status: str, parent_run_id: str = "parent-run") -> AgentEvent:
    payload = {
        "delegation_id": "delegation-1",
        "status": status,
        "summary": "有限结果",
        "diagnostics": ["有限诊断"],
    }
    return AgentEvent(
        event_type,
        payload=payload if event_type == EventType.SUBAGENT_FINISHED else None,
        metadata={
            "delegation_id": "delegation-1",
            "parent_run_id": parent_run_id,
            "child_run_id": "child-run",
            "attempt_id": "attempt",
            "profile": "read_only",
            "task_label": "检查恢复",
            "subagent_status": status,
            "child_phase": status,
        },
        parent_run_id=parent_run_id,
    )


@pytest.mark.asyncio
async def test_parent_events_are_persisted_in_order_and_drained(session_factory, tmp_path):
    from codeagent.session.persistence import JsonFileStore

    store = JsonFileStore(tmp_path / "sessions")
    session = session_factory(store=store, session_id="parent")

    session._emit(_event(EventType.SUBAGENT_QUEUED, status="queued"), "parent-run")
    session._emit(_event(EventType.SUBAGENT_STARTED, status="running"), "parent-run")
    session._emit(
        _event(EventType.SUBAGENT_FINISHED, status="completed"),
        "parent-run",
    )
    await session._persistence.drain_subagent_records()

    records = store.load_subagent_records("parent")
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].child_run_id == "child-run"
    entries = [
        json.loads(line)
        for line in (tmp_path / "sessions" / "parent.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["status"] for entry in entries[1:]] == ["queued", "running", "completed"]


@pytest.mark.asyncio
async def test_wrong_parent_event_is_not_persisted(session_factory, tmp_path):
    from codeagent.session.persistence import JsonFileStore

    store = JsonFileStore(tmp_path / "sessions")
    session = session_factory(store=store, session_id="parent")
    session._emit(_event(EventType.SUBAGENT_QUEUED, status="queued", parent_run_id="other"), "parent-run")
    await session._persistence.drain_subagent_records()
    assert store.load_subagent_records("parent") == []


@pytest.mark.asyncio
async def test_record_write_failure_is_isolated_from_parent_event(session_factory):
    from codeagent.session.persistence import MemoryStore

    class FailingStore(MemoryStore):
        def append_subagent_record(self, session_id, record):
            raise OSError("record disk unavailable")

    store = FailingStore()
    session = session_factory(store=store, session_id="parent")
    session._emit(_event(EventType.SUBAGENT_QUEUED, status="queued"), "parent-run")

    await session._persistence.drain_subagent_records()

    assert session.subagent_records[0].status == "queued"
    assert store.load_subagent_records("parent") == []
    assert any("record disk unavailable" in item for item in session._persistence.subagent_record_diagnostics)
