"""cancellation behavior tests."""

from tests.session.behavior.fixtures import *  # noqa: F401,F403


async def test_abort_cancels_and_emits_run_cancelled():
    """abort:取消当前 run,RUN_CANCELLED 事件 + 历史回滚。"""
    started = asyncio.Event()

    class SlowModel(FakeClient):
        async def stream(self, messages, tools=None):
            started.set()
            await asyncio.Event().wait()
            async for ev in super().stream(messages, tools):
                yield ev

    sess = _session(SlowModel(response="x"))
    seen: list = []
    sess.subscribe(seen.append)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("跑"))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        sess.abort()
        with pytest.raises(asyncio.CancelledError):
            await task

    await (scenario())
    assert EventType.RUN_CANCELLED in _event_types(seen)
    assert sess.history == []



async def test_steer_injects_message():
    """运行中 steer:注入消息成为后续轮次的 user 消息(回归:事件确定性)。"""

    started = asyncio.Event()
    release = asyncio.Event()

    class SlowFirstModel(FakeClient):
        """只暂停首轮模型调用,由测试事件显式释放。"""

        async def stream(self, messages, tools=None):
            if not self.call_history:
                started.set()
                await release.wait()
            async for ev in super().stream(messages, tools):
                yield ev

    model = SlowFirstModel(
        steps=[
            {"content": "", "tool_calls": [{"name": "bash", "args": {"command": "echo a"}, "id": "s1", "type": "tool_call"}]},
            {"content": "已处理注入"},
        ]
    )
    sess = _session(model)

    async def scenario() -> None:
        task = asyncio.create_task(sess.run("开始"))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        sess.steer("运行中注入")
        release.set()
        await task

    await (scenario())
    users = [m.content for m in sess.history if m.role == "user"]
    assert "运行中注入" in users
    # 注入消息进入第二轮模型输入(下一轮循环前消费,而非事后追加)
    second_call = model.call_history[1]["messages"]
    assert any("运行中注入" in (m.get("content") or "") for m in second_call)

