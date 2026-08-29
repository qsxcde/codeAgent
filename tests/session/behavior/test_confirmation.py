"""confirmation behavior tests."""

from tests.session.behavior.fixtures import *  # noqa: F401,F403


async def test_respond_approval_approves_and_executes():
    """批准:确认请求事件先于工具结果;响应后工具执行、结果非错误。"""
    sess = _session_with_policy(_ask_model(), policy=_StubPolicy({"bash": "ask"}))
    seen: list = []
    confirmation_ready = _subscribe_confirmation(sess, seen)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        await asyncio.wait_for(confirmation_ready.wait(), timeout=1.0)
        payload = next(
            e for e in seen if e.type == EventType.CONFIRMATION_REQUESTED
        ).payload
        assert payload["tool"] == "bash" and payload["reason"] == "stub:bash"
        assert payload["tool_call_id"] == "c1"
        assert not any(e.type == EventType.TOOL_RESULT for e in seen)  # 未响应前不执行
        sess.respond_approval(payload["request_id"], True)
        await task

    await (scenario())
    results = [e for e in seen if e.type == EventType.TOOL_RESULT]
    assert results and results[-1].metadata["error"] is False
    assert "ok" in results[-1].payload



async def test_respond_approval_rejects_and_fills_error():
    """拒绝:工具不执行,结果回填「用户拒绝执行」错误(模型可见)。"""
    sess = _session_with_policy(_ask_model(), policy=_StubPolicy({"bash": "ask"}))
    seen: list = []
    confirmation_ready = _subscribe_confirmation(sess, seen)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        await asyncio.wait_for(confirmation_ready.wait(), timeout=1.0)
        payload = next(
            e for e in seen if e.type == EventType.CONFIRMATION_REQUESTED
        ).payload
        sess.respond_approval(payload["request_id"], False)
        await task

    await (scenario())
    results = [e for e in seen if e.type == EventType.TOOL_RESULT]
    assert results and results[-1].metadata["error"] is True
    assert "用户拒绝执行" in results[-1].payload
    assert "ok" not in results[-1].payload



async def test_abort_while_waiting_confirmation_cancels_without_hanging():
    """等待确认期间 abort:无悬挂,取消语义收尾,工具未执行。"""
    sess = _session_with_policy(_ask_model(), policy=_StubPolicy({"bash": "ask"}))
    seen: list = []
    confirmation_ready = _subscribe_confirmation(sess, seen)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        await asyncio.wait_for(confirmation_ready.wait(), timeout=1.0)
        sess.abort()
        with pytest.raises(asyncio.CancelledError):
            await task

    await (scenario())
    assert EventType.RUN_CANCELLED in [e.type for e in seen]
    assert not any(e.type == EventType.TOOL_RESULT for e in seen)


async def test_confirmation_timeout_fails_with_structured_error():
    sess = _session_with_policy(
        _ask_model(),
        policy=_StubPolicy({"bash": "ask"}),
        confirmation_timeout=0.01,
    )
    seen: list = []
    sess.subscribe(seen.append)

    await sess.run("跑")

    error = next(event for event in seen if event.type == EventType.ERROR)
    assert error.metadata["error_code"] == "confirmation_error"
    assert error.metadata["phase"] == "awaiting_confirmation"
    assert sess.last_failure["error_code"] == "confirmation_error"


async def test_stale_confirmation_response_is_ignored_without_waking_new_request():
    from codeagent.session.runtime.confirmation import ConfirmationCoordinator

    coordinator = ConfirmationCoordinator()
    assert coordinator.register("first") is True
    assert coordinator.active_request_ids == ("first",)
    first = asyncio.create_task(coordinator.wait("first"))
    assert coordinator.respond("first", True) is True
    assert await first is True
    assert coordinator.active_request_ids == ()
    assert coordinator.respond("first", False) is False

    assert coordinator.register("second") is True
    second = asyncio.create_task(coordinator.wait("second"))
    await asyncio.sleep(0)
    assert coordinator.respond("first", False) is False
    assert not second.done()
    assert coordinator.respond("second", False) is True
    assert await second is False
    assert coordinator.active_request_ids == ()
    assert coordinator.respond("second", True) is False


async def test_confirmation_timeout_removes_request_and_wakes_waiter():
    from codeagent.session.runtime.confirmation import (
        ConfirmationCoordinator,
        ConfirmationTimeoutError,
    )

    coordinator = ConfirmationCoordinator()
    with pytest.raises(ConfirmationTimeoutError):
        await coordinator.wait("expiring", timeout=0.001)

    assert coordinator.active_request_ids == ()
    assert coordinator.respond("expiring", True) is False


async def test_wait_timeout_applies_to_request_registered_without_timer():
    from codeagent.session.runtime.confirmation import (
        ConfirmationCoordinator,
        ConfirmationTimeoutError,
    )

    coordinator = ConfirmationCoordinator()
    assert coordinator.register("late") is True
    with pytest.raises(ConfirmationTimeoutError):
        await coordinator.wait("late", timeout=0.001)
    assert coordinator.active_request_ids == ()
