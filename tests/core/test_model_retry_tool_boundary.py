from __future__ import annotations

import httpx
import pytest

from codeagent.ai.transport.openai_compat import OpenAICompatClient
from codeagent.app.composition.model.port import ChatModelPort
from codeagent.core.context.model import AgentContext
from codeagent.core.contracts.messages import ToolResult
from codeagent.core.orchestration.config import AgentLoopConfig
from codeagent.core.orchestration.loop import run_agent_loop


class _CountingTool:
    name = "write"
    description = "write one value"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
        self.calls += 1
        return ToolResult(tool_call_id, "written", name=self.name, cleanup_confirmed=True)


@pytest.mark.anyio
async def test_model_retry_does_not_repeat_tool_execution() -> None:
    calls = 0
    tool_response = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
        '"function":{"name":"write","arguments":"{}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    final_response = (
        'data: {"choices":[{"delta":{"content":"done"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        body = tool_response if calls == 2 else final_response
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    provider = OpenAICompatClient(
        base_url="https://api.example.test",
        api_key="sk-test",
        model="test-model",
        max_retries=1,
    )
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tool = _CountingTool()
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr("asyncio.sleep", lambda _delay: _completed())
            messages = await run_agent_loop(
                AgentContext(),
                AgentLoopConfig(model=ChatModelPort(provider), tools=[tool]),
                "write it",
                recursion_limit=3,
            )
    finally:
        await provider.aclose()

    assert calls == 3
    assert tool.calls == 1
    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert messages[-1].content == "done"


async def _completed() -> None:
    return None
