from __future__ import annotations

import asyncio

import pytest

from codeagent.core.agent import Agent
from codeagent.core.context import AgentContext
from codeagent.core.events import EventType
from codeagent.core.messages import Message
from codeagent.core.ports import AgentLoopConfig, StreamEvent


class _Model:
    model_id = "test-model"

    def __init__(self, responses):
        self.responses = list(responses)

    def stream(self, messages, tools=None):
        async def iterator():
            response = self.responses.pop(0)
            if response:
                yield StreamEvent(type="content", text=response)
            yield StreamEvent(type="finish", finish_reason="stop")

        return iterator()


class _GatedModel(_Model):
    def __init__(self, responses):
        super().__init__(responses)
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    def stream(self, messages, tools=None):
        self.calls.append(list(messages))

        async def iterator():
            self.started.set()
            await self.release.wait()
            response = self.responses.pop(0)
            yield StreamEvent(type="content", text=response)
            yield StreamEvent(type="finish", finish_reason="stop")

        return iterator()


class _Tool:
    name = "lookup"
    description = "lookup"
    parameters = {"type": "object"}

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        self.started.set()
        await self.release.wait()
        return "ok"


class _ToolModel:
    model_id = "test-model"

    def __init__(self):
        self.calls = []

    def stream(self, messages, tools=None):
        self.calls.append(list(messages))
        call_number = len(self.calls)

        async def iterator():
            if call_number == 1:
                yield StreamEvent(
                    type="tool_call",
                    tool_index=0,
                    tool_name="lookup",
                    tool_id="call-1",
                    arguments={},
                )
            else:
                yield StreamEvent(type="content", text="done")
            yield StreamEvent(type="finish", finish_reason="stop")

        return iterator()


async def test_agent_prompt_updates_context_and_notifies_subscribers() -> None:
    agent = Agent(AgentContext(), AgentLoopConfig(model=_Model(["hello"])))
    events = []
    unsubscribe = agent.subscribe(events.append)

    await (agent.prompt("hi"))
    unsubscribe()

    assert [message.content for message in agent.context.messages] == ["hi", "hello"]
    assert events[0].type == EventType.AGENT_START
    assert events[-1].type == EventType.AGENT_END


async def test_agent_events_carry_the_configured_run_id() -> None:
    agent = Agent(
        AgentContext(),
        AgentLoopConfig(model=_Model(["hello"])),
        run_id="run-1",
    )
    events = []
    agent.subscribe(events.append)

    await agent.prompt("hi")

    assert events
    assert all(event.run_id == "run-1" for event in events)
    assert all(event.metadata["run_id"] == "run-1" for event in events)


async def test_agent_continue_rejects_assistant_tail() -> None:
    context = AgentContext(messages=[Message(role="assistant", content="done")])
    agent = Agent(context, AgentLoopConfig(model=_Model(["retry"])))

    with pytest.raises(ValueError, match="assistant"):
        await (agent.continue_())


async def test_agent_follow_up_waits_for_active_run_and_starts_next_turn() -> None:
    async def scenario() -> None:
        model = _GatedModel(["first", "second"])
        agent = Agent(AgentContext(), AgentLoopConfig(model=model))
        first = asyncio.create_task(agent.prompt("hi"))
        await model.started.wait()
        follow_up = asyncio.create_task(agent.follow_up("next"))
        model.release.set()
        await first
        messages = await follow_up

        assert messages is not None
        assert [message.content for message in agent.context.messages] == [
            "hi",
            "first",
            "next",
            "second",
        ]

    await (scenario())


async def test_agent_steer_is_injected_after_tool_batch() -> None:
    async def scenario() -> None:
        model = _ToolModel()
        tool = _Tool()
        agent = Agent(
            AgentContext(tools=[tool]),
            AgentLoopConfig(model=model, tools=[tool]),
        )
        running = asyncio.create_task(agent.prompt("hi"))
        await tool.started.wait()
        agent.steer("focus on the error")
        tool.release.set()
        await running

        assert [message.content for message in agent.context.messages] == [
            "hi",
            "",
            "ok",
            "focus on the error",
            "done",
        ]
        assert model.calls[1][-1].role == "user"
        assert model.calls[1][-1].content == "focus on the error"

    await (scenario())


async def test_agent_abort_cancels_run_without_committing_partial_messages() -> None:
    async def scenario() -> None:
        model = _GatedModel(["never committed"])
        agent = Agent(AgentContext(), AgentLoopConfig(model=model))
        events = []
        agent.subscribe(events.append)
        running = asyncio.create_task(agent.prompt("cancel me"))
        await model.started.wait()
        assert agent.abort() is True
        with pytest.raises(asyncio.CancelledError):
            await running

        assert agent.context.messages == []
        assert any(event.type == EventType.ABORTED for event in events)
        assert agent.abort() is False

    await (scenario())


async def test_agent_discards_steer_messages_when_run_is_cancelled() -> None:
    async def scenario() -> None:
        model = _GatedModel(["first", "second"])
        agent = Agent(AgentContext(), AgentLoopConfig(model=model))
        running = asyncio.create_task(agent.prompt("hi"))
        await model.started.wait()
        agent.steer("stale after cancellation")
        assert agent.abort() is True
        with pytest.raises(asyncio.CancelledError):
            await running

        assert agent._config.steer_queue == []
        model.release.set()
        await agent.prompt("next")

        assert all(
            message.content != "stale after cancellation"
            for message in agent.context.messages
        )


    await (scenario())


async def test_agent_steer_not_consumed_by_a_later_independent_run() -> None:
    async def scenario() -> None:
        model = _GatedModel(["first", "second"])
        agent = Agent(AgentContext(), AgentLoopConfig(model=model))
        running = asyncio.create_task(agent.prompt("hi"))
        await model.started.wait()
        agent.steer("too late")
        model.release.set()
        await running
        await agent.prompt("next")

        assert all(message.content != "too late" for message in agent.context.messages)

    await (scenario())


async def test_cancelled_follow_up_is_removed_without_starting_a_new_turn() -> None:
    async def scenario() -> None:
        model = _GatedModel(["first", "should not run"])
        agent = Agent(AgentContext(), AgentLoopConfig(model=model))
        running = asyncio.create_task(agent.prompt("hi"))
        await model.started.wait()
        follow_up = asyncio.create_task(agent.follow_up("cancelled follow-up"))
        await asyncio.sleep(0)
        follow_up.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follow_up

        model.release.set()
        await running

        assert len(model.calls) == 1
        assert all(
            message.content != "cancelled follow-up"
            for message in agent.context.messages
        )

    await (scenario())
