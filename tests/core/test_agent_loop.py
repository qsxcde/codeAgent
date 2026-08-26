from __future__ import annotations

import asyncio

from codeagent.core.context import AgentContext
from codeagent.core.execution import ToolExecutionRuntime
from codeagent.core.events import EventType
from codeagent.core.loop import run_agent_loop, run_agent_loop_continue
from codeagent.core.messages import Message, ToolCall, ToolResult
from codeagent.core.ports import AgentLoopConfig, StreamEvent, ToolDecision


class _Model:
    model_id = "test-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, messages, tools=None):
        self.calls.append(list(messages))

        async def iterator():
            response = self.responses.pop(0)
            if response.get("content"):
                yield StreamEvent(type="content", text=response["content"])
            for call in response.get("tool_calls", []):
                yield StreamEvent(
                    type="tool_call",
                    tool_index=call.get("index", 0),
                    tool_name=call["name"],
                    tool_id=call["id"],
                    arg_delta=call.get("args", "{}"),
                )
            yield StreamEvent(type="finish", finish_reason="stop")

        return iterator()


class _Tool:
    name = "read"
    description = "read"
    parameters = {"type": "object"}

    def __init__(self):
        self.calls = []

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        self.calls.append((tool_call_id, arguments))
        return ToolResult(tool_call_id, "tool result", name=self.name)


class _ConcurrencyTool:
    def __init__(self, name: str, active_ref: list[int], delay: float = 0.01):
        self.name = name
        self.description = name
        self.parameters = {"type": "object"}
        self.delay = delay
        self.active_ref = active_ref
        self.active = 0
        self.max_active = 0

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        self.active += 1
        self.active_ref[0] += 1
        self.active_ref[1] = max(self.active_ref[1], self.active_ref[0])
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(self.delay)
        self.active -= 1
        self.active_ref[0] -= 1
        return ToolResult(tool_call_id, self.name, name=self.name)


class _TwoToolModel:
    model_id = "test-model"

    def __init__(self):
        self.calls = 0

    def stream(self, messages, tools=None):
        self.calls += 1
        call_number = self.calls

        async def iterator():
            if call_number == 1:
                for index, name in enumerate(("a", "b")):
                    yield StreamEvent(
                        type="tool_call",
                        tool_index=index,
                        tool_name=name,
                        tool_id=f"c{index}",
                        arguments={},
                    )
            else:
                yield StreamEvent(type="content", text="done")
            yield StreamEvent(type="finish", finish_reason="stop")

        return iterator()


def _config(model, tool=None, **kwargs):
    return AgentLoopConfig(model=model, tools=[tool] if tool else [], **kwargs)


def test_run_agent_loop_returns_new_messages_and_agent_events():
    model = _Model([{"content": "hello"}])
    context = AgentContext()
    events = []

    new_messages = asyncio.run(
        run_agent_loop(context, _config(model), "hi", emit=events.append)
    )

    assert [message.role for message in new_messages] == ["user", "assistant"]
    assert context.messages == []
    assert [event.type for event in events] == [
        EventType.AGENT_START,
        EventType.TURN_START,
        EventType.MESSAGE_START,
        EventType.MESSAGE_UPDATE,
        EventType.MESSAGE_END,
        EventType.TURN_END,
        EventType.AGENT_END,
    ]


def test_run_agent_loop_continue_reuses_context_without_duplicate_prompt():
    model = _Model([{"content": "first"}, {"content": "second"}])
    context = AgentContext()
    asyncio.run(run_agent_loop(context, _config(model), "hi"))
    context.messages.extend(model.calls[0])

    new_messages = asyncio.run(
        run_agent_loop_continue(context, _config(model), emit=lambda _: None)
    )

    assert [message.content for message in new_messages] == ["second"]
    assert sum(message.content == "hi" for message in model.calls[-1]) == 1


def test_run_agent_loop_transform_and_before_hook_control_tools():
    tool = _Tool()
    model = _Model(
        [
            {"tool_calls": [{"name": "read", "id": "c1", "args": "{}"}]},
            {"content": "blocked"},
        ]
    )
    transformed = []

    async def transform(messages):
        transformed.append(list(messages))
        return [*messages, Message(role="user", content="context-only")]

    async def before(call, _context):
        return ToolDecision.block("not allowed")

    context = AgentContext()
    new_messages = asyncio.run(
        run_agent_loop(
            context,
            _config(model, tool, transform_context=transform, before_tool_call=before),
            "read",
        )
    )

    assert transformed
    assert context.messages == []
    assert tool.calls == []
    assert any(message.role == "tool" and "not allowed" in message.content for message in new_messages)


def test_new_loop_sequential_mode_does_not_overlap_tools():
    async def scenario() -> None:
        active_ref = [0, 0]
        first = _ConcurrencyTool("a", active_ref)
        second = _ConcurrencyTool("b", active_ref)
        await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(
                model=_TwoToolModel(),
                tools=[first, second],
                tool_execution="sequential",
            ),
            "go",
        )

        assert first.max_active == 1
        assert second.max_active == 1
        assert active_ref[1] == 1

    asyncio.run(scenario())


def test_new_loop_parallel_emits_completion_order_but_backfills_call_order():
    async def scenario() -> None:
        active_ref = [0, 0]
        first = _ConcurrencyTool("a", active_ref, delay=0.03)
        second = _ConcurrencyTool("b", active_ref, delay=0.001)
        events = []
        messages = await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(
                model=_TwoToolModel(),
                tools=[first, second],
                tool_execution="parallel",
            ),
            "go",
            emit=events.append,
        )

        ended = [
            event.payload.name
            for event in events
            if event.type == EventType.TOOL_EXECUTION_END
        ]
        tool_messages = [message for message in messages if message.role == "tool"]
        assert ended == ["b", "a"]
        assert [message.content for message in tool_messages] == ["a", "b"]

    asyncio.run(scenario())


def test_new_loop_runtime_timeout_returns_structured_timeout_result():
    async def scenario() -> None:
        tool = _ConcurrencyTool("a", [0, 0], delay=0.05)
        events = []
        messages = await run_agent_loop(
            AgentContext(),
            AgentLoopConfig(
                model=_TwoToolModel(),
                tools=[tool],
                tool_runtime=ToolExecutionRuntime(max_concurrency=1),
                tool_timeout=0.001,
            ),
            "go",
            emit=events.append,
        )

        result = next(
            message
            for message in messages
            if message.role == "tool" and message.tool_call_id == "c0"
        )
        ended = next(
            event
            for event in events
            if event.type == EventType.TOOL_EXECUTION_END
            and event.payload.tool_call_id == "c0"
        )
        assert ended.payload.status == "timed_out"
        assert result.content.startswith("[工具执行超时]")

    asyncio.run(scenario())
