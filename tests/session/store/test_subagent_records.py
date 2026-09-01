"""父会话 Subagent 运行记录的存储契约。"""

from __future__ import annotations

import importlib
import json

import pytest

from codeagent.core.contracts.messages import Message


def _record(**overrides):
    module = importlib.import_module("codeagent.session.persistence.models")
    record_type = getattr(module, "SubagentRunRecord", None)
    assert record_type is not None, "session persistence must expose SubagentRunRecord"
    values = {
        "delegation_id": "delegation-1",
        "parent_run_id": "parent-run-1",
        "status": "queued",
        "phase": "queued",
        "task_label": "检查会话恢复",
        "profile": "read_only",
        "attempt_id": "attempt-1",
    }
    values.update(overrides)
    return record_type(**values)


@pytest.mark.parametrize("backend", ["jsonl", "memory"])
def test_subagent_records_roundtrip_without_activity_or_title_side_effect(
    tmp_path, backend
):
    from codeagent.session.persistence import JsonFileStore, MemoryStore

    store = JsonFileStore(tmp_path / "sessions") if backend == "jsonl" else MemoryStore()
    store.create("parent")
    message = Message(role="user", content="父会话问题")
    store.append_message("parent", message)
    before = store.get("parent")

    store.append_subagent_record(
        "parent",
        _record(
            child_run_id="child-run-1",
            status="completed",
            phase="completed",
            summary="子任务已完成",
            reason_code="",
            result={
                "summary": "子任务已完成",
                "findings": [{"summary": "恢复可用", "evidence_ids": []}],
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 5,
                    "reasoning_tokens": 0,
                    "cached_tokens": 0,
                },
            },
        ),
    )

    records = store.load_subagent_records("parent")
    after = store.get("parent")
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].child_run_id == "child-run-1"
    assert records[0].result["summary"] == "子任务已完成"
    assert after.last_activity_at == before.last_activity_at
    assert after.title == before.title

    if backend == "jsonl":
        lines = (tmp_path / "sessions" / "parent.jsonl").read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[-1])
        assert entry["type"] == "subagent"
        assert entry["delegationId"] == "delegation-1"
        assert len(lines) == 3


def test_nonterminal_record_becomes_abandoned_and_terminal_is_first_wins(tmp_path):
    from codeagent.session.persistence import JsonFileStore

    store = JsonFileStore(tmp_path / "sessions")
    store.create("parent")
    store.append_subagent_record("parent", _record(status="running", phase="model_wait"))
    store.append_subagent_record(
        "parent",
        _record(
            status="completed",
            phase="completed",
            summary="首次终态",
            child_run_id="child-1",
        ),
    )
    store.append_subagent_record(
        "parent",
        _record(
            status="failed",
            phase="running",
            summary="迟到冲突终态",
            reason_code="execution_failed",
        ),
    )

    records = store.load_subagent_records("parent")
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].summary == "首次终态"

    store = JsonFileStore(tmp_path / "other")
    store.create("parent")
    store.append_subagent_record("parent", _record(status="waiting_confirmation"))
    abandoned = store.load_subagent_records("parent")
    assert len(abandoned) == 1
    assert abandoned[0].status == "abandoned"
    assert abandoned[0].reason_code == "process_restarted"
    assert not abandoned[0].is_active


def test_record_payload_is_bounded_and_does_not_keep_transcript_fields():
    record = _record(
        task_label="任务\n" + "x" * 200,
        summary="s" * 20_000,
        diagnostics=("d" * 4_000,) * 20,
        result={
            "summary": "r" * 20_000,
            "prompt": "do not persist this",
            "context": [{"content": "secret context"}],
            "history": [{"role": "assistant", "content": "child transcript"}],
            "findings": [{"summary": "f" * 4_000, "evidence_ids": []}] * 40,
            "evidence": [{"evidence_id": "e1", "summary": "e" * 4_000}] * 40,
            "usage": {"input_tokens": 7},
        },
    )

    assert len(record.task_label) <= 96
    assert "\n" not in record.task_label
    assert len(record.summary) <= 16_000
    assert len(record.diagnostics) <= 8
    assert len(record.diagnostics[0]) <= 2_000
    assert "prompt" not in record.result
    assert "context" not in record.result
    assert "history" not in record.result
    assert len(record.result["findings"]) <= 16
    assert len(record.result["evidence"]) <= 32


def test_old_jsonl_without_subagent_entries_returns_empty_records(tmp_path):
    from codeagent.session.persistence import JsonFileStore

    store = JsonFileStore(tmp_path / "sessions")
    store.create("parent")
    assert store.load_subagent_records("parent") == []

    path = tmp_path / "sessions" / "parent.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "subagent", "delegationId": "missing-status"}) + "\n")
    assert store.load_subagent_records("parent") == []
