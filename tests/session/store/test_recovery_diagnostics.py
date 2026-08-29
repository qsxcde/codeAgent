"""恢复诊断与局部降级契约测试。"""

from __future__ import annotations

import json

import pytest

from codeagent.core.contracts.messages import Message
from codeagent.session.persistence import (
    JsonFileStore,
    MemoryStore,
    RecoveryDiagnostic,
    SessionRecoveryReport,
)
from codeagent.session.session_persistence import SessionPersistence


def test_recovery_report_is_typed_and_serializable() -> None:
    diagnostic = RecoveryDiagnostic(
        code="malformed_record",
        message="跳过一条损坏记录",
        impact="1 条记录未恢复",
        action="请先备份会话文件后继续使用",
    )
    report = SessionRecoveryReport(
        session_id="s1",
        status="degraded",
        diagnostics=(diagnostic,),
        valid_message_count=2,
        skipped_record_count=1,
    )

    encoded = json.dumps(report.to_dict(), ensure_ascii=False)

    assert report.can_continue is True
    assert json.loads(encoded)["diagnostics"][0]["code"] == "malformed_record"
    assert report.to_dict()["valid_message_count"] == 2


def test_memory_store_reports_healthy_and_missing_sessions() -> None:
    store = MemoryStore()
    store.create("s1")

    healthy = store.recovery_report("s1")
    missing = store.recovery_report("missing")

    assert healthy.status == "healthy"
    assert healthy.diagnostics == ()
    assert missing.status == "unavailable"
    assert missing.diagnostics[0].code == "missing_session"
    assert missing.can_continue is False


def test_session_persistence_keeps_legacy_store_without_report_port_usable() -> None:
    class LegacyMemoryStore(MemoryStore):
        recovery_report = None

    store = LegacyMemoryStore()
    store.create("s1")

    restored = SessionPersistence(store, "s1").load()

    assert restored.persisted is True


def test_json_store_reports_bad_records_and_keeps_valid_messages(tmp_path) -> None:
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    store.append_message("s1", Message(role="user", content="有效"))
    path = tmp_path / "sessions" / "s1.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")
        stream.write(
            json.dumps(
                {
                    "type": "message",
                    "id": "bad",
                    "role": "assistant",
                    "tool_calls": [{}],
                    # tool call 缺少 id，不能被伪装成有效消息。
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    report = store.recovery_report("s1")

    assert report.status == "degraded"
    assert {item.code for item in report.diagnostics} >= {
        "malformed_record",
        "invalid_message",
    }
    assert report.valid_message_count == 1
    assert report.skipped_record_count == 2
    assert [message.content for message in store.load_messages("s1")] == ["有效"]


def test_json_store_reports_missing_compaction_cut_and_falls_back_to_valid_history(tmp_path) -> None:
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    message = Message(role="user", content="有效历史")
    store.append_message("s1", message)
    path = tmp_path / "sessions" / "s1.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "compaction",
                    "id": "compact-1",
                    "parentId": message.id,
                    "firstKeptEntryId": "missing-message",
                    "timestamp": "2026-08-30T00:00:00.000",
                    "summary": "摘要",
                    "details": {},
                }
            )
            + "\n"
        )

    report = store.recovery_report("s1")
    state = store.load_context("s1")

    assert report.status == "degraded"
    assert any(item.code == "compaction_cut_missing" for item in report.diagnostics)
    assert [item.content for item in state.messages] == ["有效历史"]


def test_json_store_reports_incompatible_version_without_mutating_source(tmp_path) -> None:
    store = JsonFileStore(tmp_path / "sessions")
    store.create("s1")
    path = tmp_path / "sessions" / "s1.jsonl"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        json.dumps({"type": "session", "version": 999, "id": "s1"}) + "\n",
        encoding="utf-8",
    )

    report = store.recovery_report("s1")

    assert report.status == "unavailable"
    assert report.diagnostics[0].code == "incompatible_version"
    assert report.can_continue is False
    assert path.read_text(encoding="utf-8") != original


def test_json_store_reports_invalid_session_id_without_leaving_directory(tmp_path) -> None:
    store = JsonFileStore(tmp_path / "sessions")

    report = store.recovery_report("../outside")

    assert report.status == "unavailable"
    assert report.diagnostics[0].code == "invalid_session_id"
    assert not (tmp_path / "outside.jsonl").exists()
