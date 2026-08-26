"""fake provider:离线假模型客户端,不联网、不耗 key。

替代继承 ``BaseChatModel`` 的 ``FakeChatModel``——现在是普通 async 类,
实现自研 ``ChatClient`` 协议(见 ai/types.py),可精确控制返回内容、
工具调用与 usage 元数据,直接支撑「离线可测」卖点(design D4)。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from codeagent.ai.model.protocols import ChatClient
from codeagent.ai.model.types import ChatMessage, ChatResponse, StreamEvent, ToolCall


class FakeClient(ChatClient):
    """离线脚本化假模型。

    - 默认返回固定的 ``response`` 文本;
    - 传入 ``responses`` 时按调用顺序依次返回(耗尽后回落到 ``response``);
    - 传入 ``steps`` 时按调用顺序依次返回"步骤"(每个步骤可含 tool_calls),
      用于编排测试 ReAct 多轮循环(步骤用尽后回落到 ``response``);
    - 传入 ``tool_calls`` 时,本次(每轮)调用返回带工具调用的响应;
    - 可注入 ``usage``(input/output/thinking tokens),支撑 usage 相关测试;
    - ``bind_tools`` 为无副作用占位(记录工具名,返回 self)。
    """

    def __init__(
        self,
        response: str = "测试回复",
        responses: list[str] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        steps: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        model: str = "fake-model",
        thinking: str = "",
    ) -> None:
        self.response = response
        self.responses = list(responses or [])
        self.tool_calls = list(tool_calls or [])
        self.steps = list(steps or [])
        self.usage = usage
        self.model = model
        self.thinking = thinking
        self.bound_tools: list[str] = []
        #: 收到的调用记录(供测试断言 messages / tools)。
        self.call_history: list[dict[str, Any]] = []

    @property
    def model_id(self) -> str:
        return self.model

    def _bind_tools(self, tools: list[Any]) -> None:
        """仅记录工具名(无副作用,离线可测)。"""
        names = []
        for t in tools:
            name = getattr(t, "name", None)
            if not name:
                name = getattr(t, "__name__", None) or str(t)
            names.append(name)
        self.bound_tools = list(names)

    def bind_tools(self, tools: list[Any]) -> "FakeClient":
        """记录工具名并返回 self(框架无关;编排适配由组合根 ChatModelPort 负责)。

        - 记录工具名(无副作用,离线可测);
        - 组合根(app/composition/model_factory.py)拿到 self 后经 ``ChatModelPort`` 适配,
          供自研 ReAct 循环消费。
        """
        self._bind_tools(tools)
        return self

    # -- 脚本消费 ----------------------------------------------------------

    def _generate(self, messages: list[ChatMessage], **kwargs: Any) -> ChatResponse:
        """同步生成钩子:供测试子类覆盖以模拟异常(与旧 FakeChatModel 对齐)。

        编排桥接层(Runnable)与直接调用都会走这里,保证错误路径可测。
        """
        content, script_tool_calls = self._next_script()
        tool_calls = [
            ToolCall(
                id=tc.get("id", f"call_{i}"),
                name=tc.get("name", ""),
                arguments=(
                    tc.get("args_json")
                    or (json.dumps(tc.get("args", {}), ensure_ascii=False))
                ),
            )
            for i, tc in enumerate(script_tool_calls or [])
        ]
        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            usage=self.usage,
            finish_reason="tool_calls" if tool_calls else "stop",
            model=self.model,
        )

    def _next_script(self) -> tuple[str, list[dict[str, Any]] | None]:
        """消费 steps / responses / 兜底 response,返回 (content, tool_calls)。"""
        if self.steps:
            step = self.steps.pop(0)
            return step.get("content", ""), step.get("tool_calls")
        if self.responses:
            return self.responses.pop(0), None
        return self.response, (self.tool_calls if self.tool_calls else None)

    # -- 协议实现 ----------------------------------------------------------

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: list[Any] | None = None,
        *,
        stream: bool = False,
    ) -> ChatResponse:
        """按脚本返回一轮响应(不联网)。"""
        if tools is not None:
            self.bind_tools(tools)
        self.call_history.append(
            {"messages": [m.to_api_dict() for m in messages], "bound_tools": list(self.bound_tools)}
        )
        return self._generate(messages)

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式:把脚本响应拆成 content / tool_call_arg / finish 事件(离线)。

        tool_calls 步骤产出 tool_call_arg 事件(参数完整一次性发出),
        供 astream 桥接层累积组装完整 tool_calls。
        """
        resp = await self.generate(messages, tools)
        if self.thinking:
            yield StreamEvent(type="thinking", text=self.thinking)
        if resp.content:
            yield StreamEvent(type="content", text=resp.content)
        for i, tc in enumerate(resp.tool_calls):
            yield StreamEvent(
                type="tool_call_arg",
                tool_index=i,
                arg_delta=tc.arguments,
                tool_name=tc.name,
                tool_id=tc.id,
            )
        if resp.usage:
            yield StreamEvent(type="usage", usage=resp.usage)
        yield StreamEvent(type="finish", finish_reason=resp.finish_reason)


PROVIDER_NAME = "fake"


def make_llm(
    cfg: Any = None,
    spec: Any = None,
    *,
    reasoning_effort: str | None = None,
) -> FakeClient:
    """返回一个离线假模型(忽略 cfg/spec/effort,仅保持签名统一)。"""
    return FakeClient(response="测试回复")
