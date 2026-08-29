from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel

from codeagent.app.composition.tools.adapter import AgentToolAdapter


class _Args(BaseModel):
    text: str


class _LegacyTool:
    name = "echo"
    description = "echo text"
    Args = _Args

    def invoke(self, args: _Args) -> str:
        return args.text


class _FailingTool(_LegacyTool):
    def invoke(self, args: _Args) -> str:
        raise RuntimeError("token=secret-value")


class _HookedTool(_LegacyTool):
    def __init__(self) -> None:
        self.received: tuple[object, object] | None = None

    async def ainvoke(self, args: _Args, *, signal=None, on_update=None) -> str:
        self.received = (signal, on_update)
        return args.text


async def test_agent_tool_adapter_exposes_schema_and_async_execute() -> None:
    adapter = AgentToolAdapter(_LegacyTool())

    result = await (adapter.execute("c1", {"text": "hello"}))

    assert adapter.name == "echo"
    assert adapter.parameters["type"] == "object"
    assert not hasattr(adapter, "Args")
    assert not hasattr(adapter, "invoke")
    assert result.content == "hello"
    assert result.tool_call_id == "c1"


async def test_agent_tool_adapter_logs_unexpected_execution_failure(caplog) -> None:
    """返回模型可见失败时，应用仍必须记录完整的原始异常。"""
    adapter = AgentToolAdapter(_FailingTool())

    with caplog.at_level(logging.ERROR, logger="codeagent.app"):
        result = await (adapter.execute("c1", {"text": "hello"}))

    assert result.error is True
    assert "[工具执行出错]" in result.content
    record = caplog.records[-1]
    assert record.getMessage() == "工具执行失败"
    assert record.exc_info is not None


async def test_agent_tool_adapter_forwards_optional_runtime_hooks() -> None:
    tool = _HookedTool()
    adapter = AgentToolAdapter(tool)
    signal = object()
    on_update = object()

    result = await adapter.execute(
        "c1", {"text": "hello"}, signal=signal, on_update=on_update
    )

    assert result.content == "hello"
    assert tool.received == (signal, on_update)
