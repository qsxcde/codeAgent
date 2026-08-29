from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.contract


class _EchoTool:
    name = "echo"
    description = "echo"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        from codeagent.core.contracts.messages import ToolExecutionStatus, ToolResult

        return ToolResult(
            tool_call_id,
            "original",
            name=self.name,
            status=ToolExecutionStatus.OK,
        )


def _config(model, **kwargs):
    from codeagent.app.container import ChatModelPort
    from codeagent.core import AgentLoopConfig

    return AgentLoopConfig(model=ChatModelPort(model), tools=[_EchoTool()], **kwargs)


async def test_multiple_lifecycle_hooks_keep_order_and_ignore_return_values():
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.core import Agent, AgentContext

    seen: list[str] = []

    def first(event):
        if event.event_type == "turn_start":
            seen.append("first")
        return {"action": "block"}

    def second(event):
        if event.event_type == "turn_start":
            seen.append("second")
        return False

    agent = Agent(
        AgentContext(),
        _config(FakeClient(response="done"), lifecycle_hooks=[first, second]),
    )
    await agent.prompt("hello")

    assert seen == ["first", "second"]


async def test_context_extensions_modify_only_the_temporary_model_view():
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.core import AgentContext, Message, run_agent_loop

    model = FakeClient(response="done")
    source = AgentContext(messages=[Message(role="user", content="history")])
    calls: list[str] = []

    def transform(messages):
        calls.append("legacy")
        messages[0].content = "legacy-view"
        return messages

    def prepare(request):
        calls.append("preparer")
        request.messages[0].content = "prepared-view"
        return list(request.messages)

    await run_agent_loop(
        source,
        _config(
            model,
            transform_context=transform,
            context_preparer=prepare,
        ),
        "prompt",
    )

    assert calls == ["legacy", "preparer"]
    assert source.messages[0].content == "history"
    assert model.call_history[0]["messages"][0]["content"] == "prepared-view"


async def test_after_tool_hook_result_is_sent_to_next_model_request():
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.core import AgentContext, run_agent_loop

    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "echo", "args": {}, "id": "c1"}]},
            {"content": "done"},
        ]
    )
    seen: list[str] = []

    async def after(call, result, context):
        seen.append(result.content)
        result.content = "modified"
        return result

    messages = await run_agent_loop(
        AgentContext(),
        _config(model, after_tool_call=after),
        "run",
    )

    tool_message = next(message for message in messages if message.role == "tool")
    assert seen == ["original"]
    assert tool_message.content == "modified"
    assert model.call_history[1]["messages"][-1]["content"] == "modified"


@pytest.mark.parametrize("phase", ["before", "after"])
async def test_tool_extension_failure_stops_the_turn_with_error_event(phase):
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.core import AgentContext, run_agent_loop

    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "echo", "args": {}, "id": "c1"}]},
            {"content": "must not be requested"},
        ]
    )
    events = []

    def broken(*args):
        raise RuntimeError(f"{phase} extension failed")

    kwargs = {"before_tool_call" if phase == "before" else "after_tool_call": broken}
    with pytest.raises(RuntimeError, match="extension failed"):
        await run_agent_loop(
            AgentContext(),
            _config(model, **kwargs),
            "run",
            emit=events.append,
        )

    assert len(model.call_history) == 1
    error = next(event for event in events if event.type == "error")
    assert error.metadata["error_type"] == "RuntimeError"


async def test_cancelled_tool_extension_propagates_and_publishes_abort():
    from codeagent.ai.providers.fake import FakeClient
    from codeagent.core import AgentContext, run_agent_loop

    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "echo", "args": {}, "id": "c1"}]},
            {"content": "must not be requested"},
        ]
    )
    started = asyncio.Event()
    finished = asyncio.Event()
    events = []

    async def after(call, result, context):
        started.set()
        try:
            await asyncio.Future()
        finally:
            finished.set()

    task = asyncio.create_task(
        run_agent_loop(
            AgentContext(),
            _config(model, after_tool_call=after),
            "run",
            emit=events.append,
        )
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(finished.wait(), timeout=1)

    assert len(model.call_history) == 1
    assert any(event.type == "aborted" for event in events)
    assert not any(event.type == "error" for event in events)
