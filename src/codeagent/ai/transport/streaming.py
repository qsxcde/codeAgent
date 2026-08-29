"""流式 SSE 处理与 OpenAI-compatible 响应组装。"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from codeagent.ai.errors import classify_provider_error
from codeagent.ai.model.types import (
    ChatMessage,
    ChatResponse,
    StreamEvent,
    ToolCall,
    ToolDefinition,
)
from codeagent.ai.transport.sse import SSEParser


class OpenAICompatStreamingMixin:
    """为兼容客户端提供流式请求、重试和响应聚合能力。"""

    async def _generate_streaming(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None,
    ) -> ChatResponse:
        parser = SSEParser()
        content_parts: list[str] = []
        usage: dict[str, Any] | None = None
        finish_reason: str | None = None
        async for event in self.stream(messages, tools):
            if event.type == "content":
                content_parts.append(event.text)
            elif event.type == "tool_call_arg":
                parser.feed(
                    json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": event.tool_index or 0,
                                                "function": {
                                                    "name": event.tool_name,
                                                    "arguments": event.arg_delta,
                                                },
                                                "id": event.tool_id,
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    )
                )
            elif event.type == "usage":
                usage = event.usage
            elif event.type == "finish":
                finish_reason = event.finish_reason
        tool_calls = [
            ToolCall(
                id=tc.get("id") or uuid.uuid4().hex,
                name=tc["name"],
                arguments=tc["arguments"],
            )
            for tc in parser.assembled_tool_calls()
        ]
        return ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
            model=self._model,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式读取 SSE 帧，首帧前失败时按策略重试。"""
        body = self._body(messages, stream=True, tools=tools)
        parser = SSEParser()
        yielded = False
        for attempt in range(self._max_retries + 1):
            try:
                async for event in self._stream_attempt(body, parser):
                    yielded = True
                    yield event
                return
            except Exception as exc:  # noqa: BLE001 - retry then re-raise original
                classified = classify_provider_error(
                    exc,
                    provider=self._provider,
                    model=self._model,
                )
                if yielded or not classified.retryable or attempt == self._max_retries:
                    raise classified from exc
                await asyncio.sleep(min(2**attempt, 10.0))

    async def _stream_attempt(
        self,
        body: dict[str, Any],
        parser: SSEParser,
    ) -> AsyncIterator[StreamEvent]:
        buffer: list[str] = []
        async with self._get_client().stream(
            "POST",
            self._endpoint(),
            headers=self._headers(),
            json=body,
            timeout=self._stream_timeout,
        ) as resp:
            if not resp.is_success:
                await resp.aread()
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    if line == "" and buffer:
                        for event in from_frame("\n".join(buffer), parser):
                            yield event
                        buffer = []
                    continue
                payload = line[len("data:") :].lstrip(" ")
                if payload == "[DONE]":
                    if buffer:
                        for event in from_frame("\n".join(buffer), parser):
                            yield event
                    return
                if buffer:
                    try:
                        json.loads("\n".join(buffer))
                    except json.JSONDecodeError:
                        pass
                    else:
                        for event in from_frame("\n".join(buffer), parser):
                            yield event
                        buffer = []
                buffer.append(payload)
            if buffer:
                for event in from_frame("\n".join(buffer), parser):
                    yield event


def from_frame(data: str, parser: SSEParser) -> list[StreamEvent]:
    """将一个已拼接的 SSE data 帧交给通用解析器。"""
    data = data.strip()
    return [] if not data or data == "[DONE]" else parser.feed(data)
