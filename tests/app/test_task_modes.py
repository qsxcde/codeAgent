from __future__ import annotations

from codeagent.app.tasks.modes import (
    TaskMode,
    mode_policy,
    parse_mode_input,
)


def test_parse_mode_prefix_is_single_message_override():
    parsed = parse_mode_input("/ask explain this", sticky=TaskMode.CODE)

    assert parsed.mode is TaskMode.ASK
    assert parsed.text == "explain this"
    assert parsed.sticky is False
    assert parsed.next_sticky is TaskMode.CODE


def test_parse_mode_command_changes_sticky_mode():
    parsed = parse_mode_input("/mode plan", sticky=TaskMode.AUTO)

    assert parsed.mode is TaskMode.PLAN
    assert parsed.text == ""
    assert parsed.sticky is True
    assert parsed.next_sticky is TaskMode.PLAN


def test_read_only_mode_denies_mutation_and_allows_reads():
    base = type("Policy", (), {"decide": lambda self, name, args: None})()
    policy = mode_policy(base, TaskMode.PLAN)

    assert policy.decide("write", {"file_path": "a.py"}).action == "deny"
    assert policy.decide("read", {"file_path": "a.py"}).action != "deny"
    assert policy.decide("bash", {"command": "echo hello"}).action != "deny"
    assert policy.decide("bash", {"command": "echo hi > a.py"}).action == "deny"


async def test_plan_policy_is_enforced_by_react_tool_boundary():
    import asyncio

    from codeagent.ai.providers.fake import FakeClient
    from codeagent.app.container import ChatModelPort
    from codeagent.app.composition.tools.adapter import adapt_tools
    from codeagent.core import AgentContext, AgentLoopConfig, EventType, ToolDecision, run_agent_loop
    from codeagent.tools.atomic import EditTool, ReadTool, WriteTool

    model = FakeClient(
        steps=[
            {"content": "", "tool_calls": [{"name": "write", "args": {"file_path": "x.py", "content": "x"}, "id": "w1"}]},
            {"content": "计划已完成"},
        ]
    )
    events = []
    policy = mode_policy(None, TaskMode.PLAN)

    async def before_tool_call(call, _context):
        decision = policy.decide(call.name, call.args)
        return (
            ToolDecision.allow()
            if decision.action == "allow"
            else ToolDecision.block(decision.reason)
        )

    config = AgentLoopConfig(
        model=ChatModelPort(model),
        tools=adapt_tools([ReadTool(), WriteTool(), EditTool()]),
        before_tool_call=before_tool_call,
    )

    await (run_agent_loop(AgentContext(), config, "plan", emit=events.append))

    result = next(event for event in events if event.type == EventType.TOOL_EXECUTION_END)
    assert result.payload.status == "rejected"
