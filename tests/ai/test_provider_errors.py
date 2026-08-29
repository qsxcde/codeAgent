"""Provider 错误分类契约。"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


def _http_error(status: int, body: dict, headers: dict[str, str] | None = None):
    response = httpx.Response(status, json=body, headers=headers or {})
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response.request = request
    return httpx.HTTPStatusError(str(status), request=request, response=response)


def test_provider_error_classifies_http_kinds_and_retry_hints() -> None:
    from codeagent.ai.errors import classify_provider_error

    error = classify_provider_error(
        _http_error(
            429,
            {"error": {"message": "slow down"}},
            {"retry-after": "3", "x-request-id": "req-1"},
        ),
        provider="openai",
        model="gpt-test",
    )

    assert error.kind == "rate_limit"
    assert error.retryable is True
    assert error.status_code == 429
    assert error.retry_after == 3.0
    assert error.request_id == "req-1"
    assert error.provider == "openai"
    assert error.model == "gpt-test"

    auth = classify_provider_error(_http_error(401, {"error": "bad key"}))
    assert auth.kind == "authentication"
    assert auth.retryable is False

    server = classify_provider_error(_http_error(503, {"error": {"message": "busy"}}))
    assert server.kind == "server"
    assert server.retryable is True


def test_provider_error_distinguishes_unsupported_parameter() -> None:
    from codeagent.ai.errors import classify_provider_error

    error = classify_provider_error(
        _http_error(
            400,
            {"error": {"message": "model does not support reasoning_effort"}},
        )
    )

    assert error.kind == "unsupported_parameter"
    assert error.retryable is False
    assert "reasoning_effort" in error.detail


def test_provider_error_redacts_sensitive_detail() -> None:
    from codeagent.ai.errors import classify_provider_error

    error = classify_provider_error(
        _http_error(
            400,
            {
                "error": {
                    "message": "authorization: Bearer super-secret-token; api_key=sk-secret",
                }
            },
        )
    )
    json_fields = classify_provider_error(
        _http_error(400, {"error": {"api_key": "sk-json-secret", "token": "token-secret"}})
    )

    assert "super-secret-token" not in error.detail
    assert "sk-secret" not in error.detail
    assert "[REDACTED]" in error.detail
    assert "sk-json-secret" not in json_fields.detail
    assert "token-secret" not in json_fields.detail


def test_transport_and_timeout_errors_are_retryable() -> None:
    from codeagent.ai.errors import classify_provider_error

    request = httpx.Request("POST", "https://example.test")
    network = classify_provider_error(httpx.ConnectError("offline", request=request))
    timeout = classify_provider_error(httpx.ReadTimeout("slow", request=request))

    assert network.kind == "network"
    assert network.retryable is True
    assert timeout.kind == "timeout"
    assert timeout.retryable is True


@pytest.mark.anyio
async def test_openai_compat_generate_raises_classified_http_error() -> None:
    from codeagent.ai.transport.openai_compat import OpenAICompatClient
    from codeagent.ai.errors import ProviderError

    response = httpx.Response(
        403,
        json={"error": {"message": "forbidden"}},
        request=httpx.Request("POST", "https://example.test"),
    )
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", lambda **_kwargs: client)
        model = OpenAICompatClient(
            base_url="https://example.test",
            api_key="test",
            model="test-model",
            max_retries=0,
        )
        with pytest.raises(ProviderError) as caught:
            await model.generate([])

    assert caught.value.kind == "authentication"
    assert isinstance(caught.value, httpx.HTTPStatusError)


@pytest.mark.anyio
async def test_openai_compat_stream_raises_same_classified_http_error() -> None:
    from codeagent.ai.errors import ProviderError
    from codeagent.ai.transport.openai_compat import OpenAICompatClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "forbidden"}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", lambda **_kwargs: client)
        model = OpenAICompatClient(
            base_url="https://example.test",
            api_key="test",
            model="test-model",
            provider="openai",
            max_retries=0,
        )
        with pytest.raises(ProviderError) as caught:
            async for _ in model.stream([]):
                pass
    await client.aclose()

    assert caught.value.kind == "authentication"
    assert caught.value.provider == "openai"
    assert caught.value.model == "test-model"
    assert isinstance(caught.value, httpx.HTTPStatusError)
