from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from codeagent.ai.errors import ProviderError
from codeagent.ai.model.types import ChatMessage, StreamEvent
from codeagent.ai.transport.openai_compat import OpenAICompatClient
from codeagent.ai.transport.retry import MAX_RETRIES, retry_delay, validate_max_retries


def _client(**kwargs) -> OpenAICompatClient:
    base = {
        "base_url": "https://api.example.test",
        "api_key": "sk-test",
        "model": "test-model",
    }
    base.update(kwargs)
    return OpenAICompatClient(**base)


@pytest.mark.parametrize("value", [-1, MAX_RETRIES + 1, True, 1.0, "1"])
def test_retry_policy_rejects_invalid_max_retries(value) -> None:
    with pytest.raises(ValueError, match="max_retries"):
        validate_max_retries(value)


@pytest.mark.parametrize("value", [0, 1, MAX_RETRIES])
def test_retry_policy_accepts_bounded_integer(value) -> None:
    assert validate_max_retries(value) == value


def test_retry_delay_prefers_retry_after_and_caps_it() -> None:
    assert retry_delay(0, retry_after=3.5) == 3.5
    assert retry_delay(4, retry_after=300) == 10.0
    assert retry_delay(4, retry_after=None) == 10.0


@pytest.mark.anyio
async def test_generate_uses_bounded_retry_after_delay() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={"error": "rate limited"},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
        )

    client = _client(max_retries=1)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sleep = AsyncMock()
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr("asyncio.sleep", sleep)
            response = await client.generate([ChatMessage(role="user", content="hi")])
    finally:
        await client.aclose()

    assert response.content == "ok"
    assert calls == 2
    sleep.assert_awaited_once_with(3.0)


@pytest.mark.anyio
async def test_stream_failure_after_first_event_is_not_replayed() -> None:
    client = _client(max_retries=3)
    attempts = 0

    async def stream_attempt(_body, _parser):
        nonlocal attempts
        attempts += 1
        yield StreamEvent(type="content", text="prefix")
        raise httpx.ReadError("connection lost after prefix")

    client._stream_attempt = stream_attempt
    events: list[StreamEvent] = []
    with pytest.raises(ProviderError, match="network failure"):
        async for event in client.stream([], tools=[]):
            events.append(event)

    assert [event.text for event in events] == ["prefix"]
    assert attempts == 1
