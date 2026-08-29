"""Runtime lifecycle and snapshot tests for the observable TUI state."""

from dataclasses import replace

from codeagent.app.tui.state.model import TuiModel
from codeagent.app.tui.state.runtime import (
    RuntimePhase,
    RuntimeReducer,
    RuntimeSnapshot,
)
from codeagent.app.tui.presentation.status import StatusBar
from codeagent.core.contracts.events import AgentEvent, EventType


def test_runtime_reducer_tracks_phase_and_elapsed_operation() -> None:
    reducer = RuntimeReducer(clock=lambda: 12.5)
    snapshot = RuntimeSnapshot()

    snapshot = reducer.apply(
        snapshot,
        AgentEvent(
            EventType.SESSION_STARTED,
            payload="hello",
            metadata={"session_id": "session-1", "run_id": "run-1"},
        ),
    )
    assert snapshot.phase == RuntimePhase.WAITING_MODEL
    assert snapshot.session_id == "session-1"
    assert snapshot.run_id == "run-1"
    assert snapshot.current_operation == "等待模型响应"
    assert snapshot.phase_started_at == 12.5

    reducer._clock = lambda: 15.0
    snapshot = reducer.apply(
        snapshot,
        AgentEvent(
            EventType.TOOL_STARTED,
            payload={"name": "bash"},
            metadata={
                "session_id": "session-1",
                "run_id": "run-1",
                "tool_call_id": "call-1",
                "operation_id": "op-1",
            },
        ),
    )
    assert snapshot.phase == RuntimePhase.TOOL_RUNNING
    assert snapshot.current_operation == "bash"
    assert snapshot.tool_counts == {"running": 1}
    assert snapshot.elapsed_ms == 0


def test_runtime_reducer_ignores_stale_run_events() -> None:
    reducer = RuntimeReducer(clock=lambda: 1.0)
    snapshot = RuntimeSnapshot(
        session_id="session-1",
        run_id="run-current",
        phase=RuntimePhase.STREAMING,
        phase_started_at=0.0,
    )

    stale = reducer.apply(
        snapshot,
        AgentEvent(
            EventType.ERROR,
            payload="old failure",
            metadata={"session_id": "session-1", "run_id": "run-old"},
        ),
    )
    assert stale == snapshot

    wrong_session = reducer.apply(
        snapshot,
        AgentEvent(
            EventType.TOOL_FINISHED,
            metadata={"session_id": "session-2", "run_id": "run-current"},
        ),
    )
    assert wrong_session == snapshot


def test_runtime_reducer_does_not_duplicate_activity_for_same_run() -> None:
    reducer = RuntimeReducer(clock=lambda: 5.0)
    snapshot = RuntimeSnapshot()
    start = AgentEvent(
        EventType.SESSION_STARTED,
        payload="hello",
        metadata={"session_id": "session-1", "run_id": "run-1"},
    )
    first = reducer.apply(snapshot, start)
    second = reducer.apply(first, start)
    assert second == first


def test_status_bar_prioritizes_runtime_state_and_context() -> None:
    status = StatusBar()
    status.apply_snapshot(
        RuntimeSnapshot(
            phase=RuntimePhase.TOOL_RUNNING,
            phase_started_at=10.0,
            current_operation="bash ./long-command.sh",
            context_tokens=12_400,
            context_window=128_000,
        ),
        now=12.5,
    )
    plain = "".join(span.text for span in status.render(120)[0])
    assert "工具执行" in plain
    assert "2.5s" in plain
    assert "bash ./long-command.sh" in plain
    assert "上下文 12.4k / 128k" in plain


def test_tui_model_exposes_runtime_snapshot() -> None:
    model = TuiModel(clock=lambda: 7.0)
    model.apply(
        AgentEvent(
            EventType.SESSION_STARTED,
            payload="hello",
            metadata={"session_id": "session-1", "run_id": "run-1"},
        )
    )
    assert model.runtime.phase == RuntimePhase.WAITING_MODEL
    assert model.running is True


def test_compaction_and_restore_are_busy_phases() -> None:
    model = TuiModel(clock=lambda: 2.0)
    model.apply(AgentEvent(EventType.COMPACTION_STARTED))
    assert model.runtime.phase == RuntimePhase.COMPACTING
    assert model.running is True
    model.apply(AgentEvent(EventType.COMPACTION_FINISHED, metadata={"success": True}))
    assert model.runtime.phase == RuntimePhase.IDLE
    assert model.running is False
    model.apply(AgentEvent(EventType.RESTORE_STARTED, metadata={"session_id": "s"}))
    assert model.runtime.phase == RuntimePhase.RESTORING
    assert model.runtime.context_stale is True


def test_error_snapshot_keeps_retry_and_cleanup_diagnostics() -> None:
    model = TuiModel(clock=lambda: 3.0)
    model.apply(
        AgentEvent(
            EventType.ERROR,
            payload="tool may still be running",
            metadata={
                "retryable": False,
                "error_code": "cleanup_uncertain",
                "cleanup_uncertain": True,
                "side_effect_state": "uncertain",
            },
        )
    )
    assert model.runtime.phase == RuntimePhase.ERROR
    assert model.runtime.retryable is False
    assert model.runtime.cleanup_uncertain is True
    assert model.runtime.error_code == "cleanup_uncertain"


def test_runtime_reducer_does_not_double_count_tool_finish_and_result() -> None:
    reducer = RuntimeReducer(clock=lambda: 1.0)
    snapshot = RuntimeSnapshot()
    base = {"session_id": "s", "run_id": "r", "tool_call_id": "call-1"}
    snapshot = reducer.apply(snapshot, AgentEvent(EventType.SESSION_STARTED, metadata=base))
    snapshot = reducer.apply(snapshot, AgentEvent(EventType.TOOL_STARTED, metadata=base))
    snapshot = reducer.apply(
        snapshot,
        AgentEvent(EventType.TOOL_FINISHED, metadata={**base, "status": "ok"}),
    )
    snapshot = reducer.apply(
        snapshot,
        AgentEvent(EventType.TOOL_RESULT, metadata={**base, "status": "ok"}),
    )

    assert snapshot.tool_counts["completed"] == 1


def test_compaction_failure_has_terminal_runtime_state() -> None:
    model = TuiModel(clock=lambda: 2.0)
    model.apply(AgentEvent(EventType.COMPACTION_STARTED))
    model.apply(
        AgentEvent(
            EventType.COMPACTION_FINISHED,
            metadata={"success": False, "error_code": "compaction_failed"},
        )
    )

    assert model.runtime.phase == RuntimePhase.ERROR
    assert model.runtime.error_code == "compaction_failed"


def test_auto_compaction_skip_keeps_idle_phase_and_exposes_diagnostics() -> None:
    model = TuiModel(clock=lambda: 2.0)
    model.apply(
        AgentEvent(
            EventType.COMPACTION_STARTED,
            metadata={"trigger": "auto", "target_budget": 600},
        )
    )
    model.apply(
        AgentEvent(
            EventType.COMPACTION_FINISHED,
            metadata={
                "success": True,
                "status": "skipped",
                "reason_code": "oversized_turn",
                "before_input_tokens": 2_000,
                "input_budget": 2_000,
                "target_budget": 600,
            },
        )
    )

    assert model.runtime.phase == RuntimePhase.IDLE
    assert model.runtime.compaction_status == "skipped"
    assert model.runtime.compaction_trigger == "auto"
    assert model.runtime.compaction_reason == "oversized_turn"


def test_auto_compaction_success_updates_context_and_transcript_diagnostics() -> None:
    model = TuiModel(clock=lambda: 2.0)
    model.apply(
        AgentEvent(
            EventType.COMPACTION_STARTED,
            metadata={"trigger": "auto", "input_tokens": 1_900, "target_budget": 1_300},
        )
    )
    model.apply(
        AgentEvent(
            EventType.COMPACTION_FINISHED,
            metadata={
                "success": True,
                "trigger": "auto",
                "status": "compacted",
                "before_input_tokens": 1_900,
                "after_input_tokens": 700,
                "target_budget": 1_300,
                "summarized_turns": 4,
                "kept_turns": 2,
            },
        )
    )

    assert model.runtime.context_tokens == 700
    assert model.runtime.compaction_after_tokens == 700
    assert "1,900" in model.transcript.blocks[-1].body
    assert "700" in model.transcript.blocks[-1].body


def test_auto_compaction_persistence_uncertain_is_not_success() -> None:
    model = TuiModel(clock=lambda: 2.0)
    model.apply(AgentEvent(EventType.COMPACTION_STARTED, metadata={"trigger": "auto"}))
    model.apply(
        AgentEvent(
            EventType.COMPACTION_FINISHED,
            metadata={
                "success": False,
                "trigger": "auto",
                "status": "persistence_uncertain",
                "error_code": "persistence_uncertain",
            },
        )
    )

    assert model.runtime.phase == RuntimePhase.ERROR
    assert model.runtime.error_code == "persistence_uncertain"
    assert "持久化结果不确定" in model.transcript.blocks[-1].body
