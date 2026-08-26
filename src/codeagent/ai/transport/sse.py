"""SSE 流式解析:把 ``/chat/completions`` 帧翻译成模型流事件。

解析器只处理 OpenAI-compatible 线协议；输出使用 ``ai.model`` 的
provider 无关事件，避免 SSE 细节泄漏到 core 或应用层。
"""

from __future__ import annotations

import json

from codeagent.ai.model.types import StreamEvent


class SSEParser:
    """增量解析 SSE 数据帧并累积 tool-call 参数。"""

    def __init__(self) -> None:
        self._tool_args: dict[int, str] = {}
        self._tool_names: dict[int, str] = {}
        self._tool_ids: dict[int, str] = {}

    def feed(self, data: str) -> list[StreamEvent]:
        """解析一帧 ``data:`` 内容；``[DONE]`` 返回空列表。"""
        data = data.strip()
        if not data or data == "[DONE]":
            return []
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return []

        events: list[StreamEvent] = []
        usage = payload.get("usage")
        if usage:
            events.append(StreamEvent(type="usage", usage=usage))

        choices = payload.get("choices") or []
        if not choices:
            return events
        choice = choices[0]
        delta = choice.get("delta") or {}

        text = delta.get("content")
        if text:
            events.append(StreamEvent(type="content", text=text))

        thinking = delta.get("reasoning_content")
        if thinking:
            events.append(StreamEvent(type="thinking", text=thinking))

        tool_calls = delta.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                index = tc.get("index", 0)
                fn = tc.get("function") or {}
                name = fn.get("name")
                arg_delta = fn.get("arguments") or ""
                if name:
                    self._tool_names[index] = name
                tool_id = tc.get("id") or ""
                if tool_id:
                    self._tool_ids[index] = tool_id
                self._tool_args[index] = self._tool_args.get(index, "") + arg_delta
                events.append(
                    StreamEvent(
                        type="tool_call_arg",
                        tool_index=index,
                        arg_delta=arg_delta,
                        tool_name=name or "",
                        tool_id=tool_id,
                    )
                )

        finish = choice.get("finish_reason")
        if finish:
            events.append(StreamEvent(type="finish", finish_reason=finish))

        return events

    def assembled_tool_calls(self) -> list[dict[str, str]]:
        """返回按 index 累积的完整工具调用列表。"""
        return [
            {
                "name": self._tool_names.get(i, ""),
                "arguments": self._tool_args.get(i, ""),
                "id": self._tool_ids.get(i, ""),
            }
            for i in sorted(self._tool_args)
        ]

    @property
    def has_pending(self) -> bool:
        """是否有尚未 finish 的 tool-call 参数累积。"""
        return bool(self._tool_args)


__all__ = ["SSEParser"]
