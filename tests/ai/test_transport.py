"""OpenAICompatClient 传输层测试:请求构造 / 响应解析 / 重试 / 流式。

网络相关用 mock httpx(不发起真实请求);当前模型客户端直接对接自研协议层,不再存在 LangChain 桥接层。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from codeagent.ai.transport.openai_compat import OpenAICompatClient
from codeagent.ai.model.types import ChatMessage, ToolCall


def _client(**kwargs) -> OpenAICompatClient:
    base = dict(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        reasoning_effort="xhigh",
    )
    base.update(kwargs)
    return OpenAICompatClient(**base)


def test_model_id_and_endpoint():
    c = _client()
    assert c.model_id == "deepseek-v4-flash"
    assert c._endpoint() == "https://api.deepseek.com/chat/completions"


def test_body_includes_reasoning_effort_and_tools():
    c = _client(reasoning_effort="xhigh", max_tokens=4096)

    class FakeTool:
        name = "read"
        description = "读文件"

        class args_schema:  # noqa: N801 - 模拟 pydantic Args
            @staticmethod
            def model_json_schema():
                return {"type": "object", "properties": {"path": {"type": "string"}}}

    c.bind_tools([FakeTool()])
    body = c._body([ChatMessage(role="user", content="hi")], stream=False)

    assert body["model"] == "deepseek-v4-flash"
    assert body["reasoning_effort"] == "xhigh"  # 原样透传,不被 SDK 约束
    assert body["max_tokens"] == 4096
    assert body["stream"] is False
    assert body["tools"][0]["function"]["name"] == "read"
    assert body["tool_choice"] == "auto"


def test_message_to_api_dict_with_tool_calls():
    msg = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="read", arguments='{"file_path": "a"}')],
    )
    d = msg.to_api_dict()
    assert d["tool_calls"][0]["function"]["arguments"] == '{"file_path": "a"}'


@pytest.mark.anyio
async def test_generate_parses_response():
    c = _client()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": "hello",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {"name": "read", "arguments": '{"p": "x"}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    import httpx

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", lambda **kw: mock_client)

        resp = await c.generate([ChatMessage(role="user", content="hi")])

    assert resp.content == "hello"
    assert resp.tool_calls[0].name == "read"
    assert resp.usage["total_tokens"] == 15


@pytest.mark.anyio
async def test_generate_retries_on_429():
    """429 错误触发指数退避重试,最终成功(回归:#13)。"""
    import httpx as _httpx

    c = _client(max_retries=2)
    # 第一次 429,第二次成功
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.raise_for_status = MagicMock(side_effect=_httpx.HTTPStatusError("429", request=MagicMock(), response=resp_429))
    resp_ok = MagicMock()
    resp_ok.raise_for_status = MagicMock()
    resp_ok.json = MagicMock(return_value={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=[resp_429, resp_ok])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_httpx, "AsyncClient", lambda **kw: mock_client)
        # 加速重试(避免测试等待 2^0 + 2^1 秒)
        mp.setattr("asyncio.sleep", AsyncMock())
        resp = await c.generate([ChatMessage(role="user", content="hi")])

    assert resp.content == "ok"
    assert mock_client.post.call_count == 2


# -- SSE 帧解析异常布局(回归:#2) ------------------------------------------

class _FakeSSEResponse:
    """模拟 ``client.stream(...)`` 返回的响应:按给定行序列产出。"""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self.is_success = True

    def raise_for_status(self) -> None:
        pass

    async def aread(self) -> bytes:
        return b""

    async def __aenter__(self) -> "_FakeSSEResponse":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    def aiter_lines(self):
        async def gen():
            for line in self._lines:
                yield line

        return gen()


class _FakeStreamingClient:
    """mock ``httpx.AsyncClient``:仅实现 ``stream`` 上下文,喂入 SSE 行序列。"""

    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self) -> "_FakeStreamingClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    def stream(self, method, url, **kwargs) -> _FakeSSEResponse:
        return _FakeSSEResponse(self._lines)


async def _collect_stream(lines: list[str]) -> list[tuple]:
    """用 mock httpx 跑 ``OpenAICompatClient.stream``,返回 (type, text, finish_reason)。"""
    import httpx

    c = _client()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", lambda **kw: _FakeStreamingClient(lines))

        async def _run():
            return [(e.type, e.text, e.finish_reason) async for e in c.stream([], tools=[])]

        return await _run()


async def test_stream_done_consecutive_without_blank_line():
    """finish 帧 + `data: [DONE]` 连发(无空行):先 flush 前一帧再终止,事件不丢(回归:#2)。"""
    events = await _collect_stream(
        [
            'data: {"choices": [{"delta": {"content": "hello"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
            "",
        ]
    )
    assert ("content", "hello", None) in events
    assert ("finish", "", "stop") in events


async def test_stream_back_to_back_frames_without_blank_line():
    """帧间无空行的两条完整 JSON data 行:分别解析,不拼接成非法 JSON(回归:#2)。"""
    events = await _collect_stream(
        [
            'data: {"choices": [{"delta": {"content": "hello"}}]}',
            'data: {"choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
            "",
        ]
    )
    assert ("content", "hello", None) in events
    assert ("content", " world", None) in events
    assert ("finish", "", "stop") in events


async def test_stream_flushes_trailing_buffer_on_close():
    """末帧无空行即断开:流结束 flush 残留 buffer,finish 不丢(回归:#2)。"""
    events = await _collect_stream(
        [
            'data: {"choices": [{"delta": {"content": "hi"}}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        ]
    )
    assert ("content", "hi", None) in events
    assert ("finish", "", "stop") in events


# -- 流式韧性 / stream_options / 连接复用(H6 / M2 / M5 / M6) ----------------

from contextlib import contextmanager


@contextmanager
def _patch_async_client(handler):
    """把 OpenAICompatClient 的底层 AsyncClient 换成带 MockTransport 的客户端。"""
    import httpx as _httpx

    transport = _httpx.MockTransport(handler)
    prebuilt = _httpx.AsyncClient(transport=transport, timeout=_httpx.Timeout(10.0))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_httpx, "AsyncClient", lambda **kw: prebuilt)
        yield prebuilt


@pytest.mark.anyio
async def test_stream_error_includes_body_details():
    """流式 401:先 aread 再 raise,错误响应体细节可读(H6)。"""
    import httpx

    c = _client()
    with _patch_async_client(
        lambda r: httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    ):
        with pytest.raises(httpx.HTTPStatusError) as ei:
            async for _ in c.stream([], tools=[]):
                pass
    # body 已被 aread:细节可读,未被 ResponseNotRead 挡住
    assert "Invalid API key" in ei.value.response.text


@pytest.mark.anyio
async def test_stream_retries_on_429():
    """流式 429 触发指数退避重试,最终成功(H6)。"""
    import httpx

    calls = {"n": 0}
    ok_body = (
        'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200, content=ok_body.encode(), headers={"content-type": "text/event-stream"}
        )

    c = _client(max_retries=2)
    with _patch_async_client(handler), pytest.MonkeyPatch.context() as mp:
        mp.setattr("asyncio.sleep", AsyncMock())
        events = [(e.type, e.text) async for e in c.stream([], tools=[])]
    assert calls["n"] == 2
    assert ("content", "ok") in events


@pytest.mark.anyio
async def test_stream_non_retryable_4xx_no_retry():
    """非重试 4xx(400)不重试,直接抛错(H6)。"""
    import httpx

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    c = _client(max_retries=3)
    with _patch_async_client(handler):
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in c.stream([], tools=[]):
                pass
    assert calls["n"] == 1  # 不重试


@pytest.mark.anyio
async def test_stream_retry_exhausted():
    """429 持续:重试耗尽后抛错(H6)。"""
    import httpx

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"error": "rate limited"})

    c = _client(max_retries=2)
    with _patch_async_client(handler), pytest.MonkeyPatch.context() as mp:
        mp.setattr("asyncio.sleep", AsyncMock())
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in c.stream([], tools=[]):
                pass
    assert calls["n"] == 3  # 初始 + 2 次重试


@pytest.mark.anyio
async def test_stream_body_includes_stream_options():
    """流式请求体携带 include_usage(M2)。"""
    import json

    import httpx

    seen: dict = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, content=b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"}
        )

    c = _client()
    with _patch_async_client(handler):
        async for _ in c.stream([], tools=[]):
            pass
    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}


@pytest.mark.anyio
async def test_generate_stream_true_uses_streaming_request():
    """generate(stream=True) 请求体 stream=true,并聚合流式响应(M5)。"""
    import json

    import httpx

    seen: dict = {}
    sse_body = (
        'data: {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, content=sse_body.encode(), headers={"content-type": "text/event-stream"}
        )

    c = _client()
    with _patch_async_client(handler):
        resp = await c.generate([], stream=True)
    assert seen["body"]["stream"] is True
    assert resp.content == "hi"
    assert resp.finish_reason == "stop"


async def test_client_reuses_connection_and_aclosable(async_resource_tracker):
    """单一 AsyncClient 复用,可显式 aclose(M6)。"""
    import asyncio

    c = async_resource_tracker(_client())
    c1 = c._get_client()
    c2 = c._get_client()
    assert c1 is c2                          # 复用同一实例
    await c.aclose()
    assert c._client is None                 # 释放后幂等
