"""ReAct 循环(自研版):for 循环驱动"模型→工具→继续/结束",事件直接 emit。

替代 langgraph 编排(2026-08-14,self-built-orchestration):
- 10 类 AgentEvent 在循环体内直接产出(翻译层消失);
- recursion_limit / abort / 工具超时均为普通代码;
- 工具结果归属靠写入顺序(见 core/messages.attach_tool_results);
- 模块顶层零副作用,可被平台直接 import。

分层约束:core 不 import config / ai / tools / session;模型与工具经
``AgentPorts`` 端口注入;事件经调用方传入的 ``emit`` 回调分发
(AgentSession 传入 ``EventBus.emit``)。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from codeagent.core.events import AgentEvent, EventType
from codeagent.core.messages import Message, ToolCall, ToolResult, attach_tool_results
from codeagent.core.ports import AgentPorts

DEFAULT_RECURSION_LIMIT = 50


class RecursionLimitError(RuntimeError):
    """循环超限(替代 GraphRecursionError):session 壳捕获后回滚并友好提示。"""

    friendly = (
        "模型连续调用工具次数过多,已自动停止本轮并清理中间状态。"
        "请重试,或换一个更明确的指令。"
    )

    def __str__(self) -> str:
        return self.friendly


async def _drain_injections(
    history: list[Message], queue: asyncio.Queue[str] | None
) -> None:
    """消费运行中注入的消息(steer):追加为 user 消息,下一轮循环前生效。"""
    if queue is None:
        return
    while not queue.empty():
        text = queue.get_nowait()
        parent = history[-1].id if history else None
        history.append(Message(role="user", content=text, parent_id=parent))


async def _call_model(
    ports: AgentPorts, emit: Callable[[AgentEvent], None], history: list[Message]
) -> Message:
    """调用模型(流式):逐增量 emit thinking/text,累积 tool_calls 与 usage。

    返回聚合后的 assistant 消息;空流(无任何块)兜底为空 content 消息。
    """
    text_parts: list[str] = []
    text_streamed = False
    thinking_parts: list[str] = []
    usage: dict[str, int] | None = None
    arg_buffers: dict[int, list[str]] = {}
    names: dict[int, str] = {}
    ids: dict[int, str] = {}
    finish_reason: str | None = None

    async for event in ports.model.stream(history, ports.tools):
        if event.type == "thinking":
            thinking_parts.append(event.text)
            emit(AgentEvent(EventType.THINKING_DELTA, payload=event.text))
        elif event.type == "content":
            text_parts.append(event.text)
            text_streamed = True
            emit(AgentEvent(EventType.TEXT_DELTA, payload=event.text))
        elif event.type == "tool_call_arg":
            index = event.tool_index or 0
            arg_buffers.setdefault(index, []).append(event.arg_delta or "")
            if event.tool_name:
                names[index] = event.tool_name
            if event.tool_id:
                ids[index] = event.tool_id
        elif event.type == "usage":
            usage = event.usage
        elif event.type == "finish":
            finish_reason = event.finish_reason

    tool_calls: list[ToolCall] = []
    for index in sorted(arg_buffers):
        raw = "".join(arg_buffers[index])
        try:
            args = json.loads(raw) if raw else {}
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}  # 流式聚合不完整/截断 JSON:回退空 dict,不崩循环
        tool_calls.append(
            ToolCall(
                id=ids.get(index) or "", name=names.get(index) or "", args=args
            )
        )

    if usage:
        emit(AgentEvent(EventType.USAGE, payload=usage))
    if not tool_calls and not text_streamed:
        # 空流兜底(对齐 v0.1 agent 节点):发 AGENT_MESSAGE(空),不发 TEXT_DELTA
        emit(AgentEvent(EventType.AGENT_MESSAGE, payload=""))
    return Message(
        role="assistant",
        content="".join(text_parts),
        tool_calls=tool_calls,
    )


async def _execute_one(
    tool: Any, call: ToolCall, timeout: float | None
) -> ToolResult:
    """执行单个工具调用,失败只返回该调用的错误结果(与 v0.1 _execute_one 对齐)。

    ``invoke`` 为同步阻塞(如 bash 120s),经 ``asyncio.to_thread`` 不阻塞事件循环;
    ``timeout`` 为附加保护(工具自带超时优先)。
    """
    try:
        args_obj = tool.Args(**call.args)
    except Exception as exc:  # noqa: BLE001 - 参数校验失败按调用失败处理
        return ToolResult(call.id, f"[工具执行出错] {exc}", error=True, name=tool.name)
    try:
        if timeout is not None:
            content = await asyncio.wait_for(
                asyncio.to_thread(tool.invoke, args_obj), timeout=timeout
            )
        else:
            content = await asyncio.to_thread(tool.invoke, args_obj)
    except Exception as exc:  # noqa: BLE001 - 单 call 兜底
        return ToolResult(call.id, f"[工具执行出错] {exc}", error=True, name=tool.name)
    return ToolResult(call.id, str(content), error=False, name=tool.name)


async def _execute_tools(
    ports: AgentPorts,
    calls: list[ToolCall],
    timeout: float | None,
) -> list[ToolResult]:
    """并行执行工具调用(gather 保序),未知工具直接生成错误结果。"""
    by_name = {t.name: t for t in ports.tools}

    async def run(call: ToolCall) -> ToolResult:
        tool = by_name.get(call.name)
        if tool is None:
            return ToolResult(
                call.id, f"[工具执行出错] 未知工具: {call.name}", error=True, name=call.name
            )
        return await _execute_one(tool, call, timeout)

    return list(await asyncio.gather(*(run(c) for c in calls)))


async def run_turn(
    ports: AgentPorts,
    emit: Callable[[AgentEvent], None],
    text: str,
    *,
    history: list[Message],
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    inject_queue: asyncio.Queue[str] | None = None,
    tool_timeout: float | None = None,
) -> list[Message]:
    """跑一轮对话(内部可含多轮 ReAct 循环),返回更新后的消息列表。

    - 事件:thinking/text 增量、tool_call / tool_result、usage 在循环体内
      emit;``session_started`` / ``turn_end`` / ``error`` / ``run_cancelled``
      由调用方(session 壳)负责;
    - 循环超限抛 ``RecursionLimitError``(调用方回滚并友好提示);
    - ``inject_queue`` 为运行中注入(steer):每轮循环前消费为 user 消息。
    """
    history = list(history)  # 调用方持有不可变视图;返回新列表
    parent = history[-1].id if history else None
    history.append(Message(role="user", content=text, parent_id=parent))

    for _ in range(max(1, recursion_limit)):
        await _drain_injections(history, inject_queue)
        assistant = await _call_model(ports, emit, history)
        history.append(assistant)
        if not assistant.tool_calls:
            break
        emit(
            AgentEvent(
                EventType.TOOL_CALL,
                payload=[c.to_dict() for c in assistant.tool_calls],
            )
        )
        results = await _execute_tools(ports, assistant.tool_calls, tool_timeout)
        attach_tool_results(history, results)
        for result in results:
            emit(
                AgentEvent(
                    EventType.TOOL_RESULT,
                    payload=result.content,
                    metadata={
                        "node": "tools",
                        "tool_call_id": result.tool_call_id,
                        "tool_name": result.name,
                        "error": result.error,
                    },
                )
            )
    else:
        raise RecursionLimitError()
    return history
