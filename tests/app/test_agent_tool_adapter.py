from __future__ import annotations

import asyncio

from pydantic import BaseModel

from codeagent.app.composition.tool_factory import AgentToolAdapter


class _Args(BaseModel):
    text: str


class _LegacyTool:
    name = "echo"
    description = "echo text"
    Args = _Args

    def invoke(self, args: _Args) -> str:
        return args.text


async def test_agent_tool_adapter_exposes_schema_and_async_execute() -> None:
    adapter = AgentToolAdapter(_LegacyTool())

    result = await (adapter.execute("c1", {"text": "hello"}))

    assert adapter.name == "echo"
    assert adapter.parameters["type"] == "object"
    assert result.content == "hello"
    assert result.tool_call_id == "c1"
