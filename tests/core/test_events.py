from codeagent.core.events import EventType


def test_new_event_constants():
    assert EventType.RUN_CANCELLED == "run_cancelled"
    assert EventType.USAGE == "usage"
    assert EventType.THINKING_DELTA == "thinking_delta"  # 回归:既有常量不受影响
