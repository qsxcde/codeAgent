"""Provider-neutral ChatClient behavior contracts."""

from __future__ import annotations

import pytest

from codeagent.ai.model.types import ChatMessage, ToolDefinition
from codeagent.ai.providers.fake import FakeClient


@pytest.mark.asyncio
async def test_chat_client_generation_and_usage_contract():
    client = FakeClient(response="reply", usage={"input_tokens": 4, "output_tokens": 2})
    tool = ToolDefinition(name="echo", description="echo", parameters={"type": "object"})

    response = await client.generate(
        [ChatMessage(role="user", content="hello")], tools=[tool]
    )

    assert response.content == "reply"
    assert response.usage == {"input_tokens": 4, "output_tokens": 2}
    assert client.bound_tools == ["echo"]
    assert client.call_history[0]["messages"][0]["content"] == "hello"


@pytest.mark.asyncio
async def test_chat_client_stream_contract_contains_terminal_event():
    client = FakeClient(response="reply", thinking="consider", usage={"output_tokens": 1})

    events = [event async for event in client.stream([ChatMessage(role="user", content="hello")])]

    assert [event.type for event in events] == ["thinking", "content", "usage", "finish"]
    assert events[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_chat_client_error_contract_preserves_provider_error():
    class FailingClient(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError, match="provider failed"):
        await FailingClient().generate([ChatMessage(role="user", content="hello")])
