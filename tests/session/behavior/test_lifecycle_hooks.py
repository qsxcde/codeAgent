from __future__ import annotations

from codeagent.core import AgentLoopConfig, LifecycleHookEvent
from codeagent.app.container import ChatModelPort
from codeagent.ai.providers.fake import FakeClient
from codeagent.session import AgentSession, EventBus


class _EchoTool:
    name = "echo"
    description = "echo"
    parameters = {"type": "object"}

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        return "ok"


async def test_session_lifecycle_hooks_cover_all_scopes_with_correlation() -> None:
    observed: list[LifecycleHookEvent] = []
    config = AgentLoopConfig(
        model=ChatModelPort(FakeClient(response="ok")),
        lifecycle_hooks=[observed.append],
    )
    session = AgentSession(config, EventBus(), session_id="session-1")

    await session.run("hello")

    scopes = {event.scope for event in observed}
    assert scopes == {"session", "turn", "model"}
    session_events = [event for event in observed if event.scope == "session"]
    assert [event.phase for event in session_events[:1]] == ["started"]
    assert session_events[-1].phase == "finished"
    assert all(event.session_id == "session-1" for event in session_events)
    assert all(event.run_id for event in observed)
    assert [message.content for message in session.history] == ["hello", "ok"]


async def test_session_lifecycle_hooks_observe_tool_scope_without_mutating_events() -> None:
    observed: list[LifecycleHookEvent] = []
    tool = _EchoTool()
    config = AgentLoopConfig(
        model=ChatModelPort(
            FakeClient(
                steps=[
                    {
                        "content": "",
                        "tool_calls": [
                            {"name": "echo", "args": {"value": "ok"}, "id": "call-1"}
                        ],
                    },
                    {"content": "done"},
                ]
            )
        ),
        tools=[tool],
        lifecycle_hooks=[observed.append],
    )
    session = AgentSession(config, EventBus(), session_id="session-2")

    await session.run("use tool")

    tool_events = [event for event in observed if event.scope == "tool"]
    assert [event.phase for event in tool_events] == ["updated", "started", "finished"]
    assert all(event.event.tool_call_id == "call-1" for event in tool_events)
    assert [message.content for message in session.history][-1] == "done"
