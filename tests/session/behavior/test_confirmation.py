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

