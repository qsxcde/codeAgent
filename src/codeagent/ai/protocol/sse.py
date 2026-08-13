"""SSE 流式解析:把 `/chat/completions` 的 SSE 帧翻译成统一事件。

自研原因(design D3):langchain SDK 会抹平 ``reasoning_content``(thinking)与
``usage.completion_tokens_details``;自研解析器把这些字段原生拿到,
且对供应商差异(usage 独立帧 / tool_calls 参数分片)宽容处理。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

#: 流式事件的类型。
StreamEventType = Literal["content", "thinking", "tool_call_arg", "finish", "usage"]


@dataclass
class StreamEvent:
    """一次 SSE 帧解析后产出的统一事件。"""

    type: StreamEventType
    text: str = ""                    # content / thinking 的文本增量
    tool_index: int | None = None     # tool_call_arg 对应的工具序号
    arg_delta: str = ""               # tool_call_arg 的参数分片(需跨帧累积)
    tool_name: str = ""               # tool_call_arg 首帧的函数名(可选)
    tool_id: str = ""                 # tool_call_arg 首帧的工具调用 id(可选,供应商真实 id)
    finish_reason: str | None = None  # finish 事件的结束原因
    usage: dict | None = None         # usage 事件的全部用量字段


class SSEParser:
    """增量解析 SSE 数据帧,累积 tool_calls 参数,产出 StreamEvent。

    用法:逐行喂入 ``data:`` 后面的 JSON(不包含 ``data: `` 前缀),
    每次 ``feed`` 返回 0..n 个事件。结束帧 ``[DONE]`` 返回空列表,
    由调用方(通常检测空 content)自行终止。
    """

    def __init__(self) -> None:
        #: tool_call 序号 → 累积中的参数分片(跨帧拼接)。
        self._tool_args: dict[int, str] = {}
        #: tool_call 序号 → 已见的函数名(可选,首帧带 name)。
        self._tool_names: dict[int, str] = {}
        #: tool_call 序号 → 供应商真实 id(可选,首帧带 id;缺失留空由桥接层回退)。
        self._tool_ids: dict[int, str] = {}

    def feed(self, data: str) -> list[StreamEvent]:
        """解析一帧 ``data:`` 内容;``[DONE]`` 返回空列表。"""
        data = data.strip()
        if not data or data == "[DONE]":
            return []
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return []  # 宽容:非 JSON 帧跳过

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

    def assembled_tool_calls(self) -> list[dict]:
        """返回按 index 累积完成的工具调用列表(参数为 JSON 字符串)。

        供流式结束(或 finish)后组装完整 ToolCall;未收到 finish 的
        部分调用也返回(宽容)。
        """
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
        """是否有尚未 finish 的 tool_call 参数累积。"""
        return bool(self._tool_args)
