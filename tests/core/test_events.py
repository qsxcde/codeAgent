from codeagent.core.events import AgentEvent, EventType


def test_new_event_constants():
    assert EventType.RUN_CANCELLED == "run_cancelled"
    assert EventType.USAGE == "usage"
    assert EventType.THINKING_DELTA == "thinking_delta"  # 回归:既有常量不受影响
    assert EventType.MODEL_REQUEST_STARTED == "model_request_started"
    assert EventType.TOOL_STARTED == "tool_started"
    assert EventType.COMPACTION_STARTED == "compaction_started"
    assert EventType.RETRY_STARTED == "retry_started"


def test_agent_event_supports_typed_runtime_metadata():
    event = AgentEvent(
        EventType.TOOL_STARTED,
        session_id="session-1",
        run_id="run-1",
        tool_call_id="call-1",
        operation_id="op-1",
        phase="tool_running",
        elapsed_ms=42,
        retryable=False,
        cleanup_uncertain=True,
        side_effect_state="uncertain",
    )
    assert event.session_id == "session-1"
    assert event.run_id == "run-1"
    assert event.tool_call_id == "call-1"
    assert event.cleanup_uncertain is True
