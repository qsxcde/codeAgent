"""tools 节点:执行 agent 请求的工具调用,结果并入消息历史。

核心实现委托 ``langgraph.prebuilt.ToolNode``——它按 tool_call_id 把
工具结果作为 ToolMessage 追加到消息历史。

langgraph-prebuilt 1.1.0 的 ToolNode 只兜底 ``ValidationError``/包装器异常,
对工具内部抛出的普通 ``ValueError`` 会直接向上传播导致整图崩溃。因此这里
在 tools 节点外层按 ``tool_call`` 粒度并行执行并独立兜底:任一调用失败只
为该调用生成错误 ToolMessage,不影响同一消息中其它调用的结果(P2-2),
并行调度与 ToolNode 原生行为一致(回归修复)。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, ToolMessage

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable


def make_tools_node(tool_executor: Runnable) -> Any:
    """把工具执行器包装成 LangGraph 可用的 tools 节点(按 call 粒度兜底)。

    - ``tool_executor`` 对编排层是黑盒(通常即 ToolNode);
    - 返回的节点为异步实现:优先按 ``tool_call`` 逐个执行(ToolNode 有
      ``tools_by_name`` 时),单调用失败仅回填自身错误;无 ``tools_by_name``
      的通用执行器走整体 ``ainvoke`` + 节点级兜底(向后兼容)。
    """

    async def tools_node(state: dict[str, Any], config=None) -> dict[str, Any]:
        messages = state.get("messages", [])
        last = messages[-1] if messages else None
        calls = getattr(last, "tool_calls", None) if isinstance(last, AIMessage) else None
        if not calls:
            return {"messages": []}

        if hasattr(tool_executor, "tools_by_name"):
            # 并行执行各 tool_call,与 ToolNode 原生 asyncio.gather 语义一致。
            # _execute_one 捕获所有 Exception,普通工具异常不使 gather 整体失败;
            # BaseException(如取消)按 asyncio 语义传播。
            tool_msgs = list(
                await asyncio.gather(
                    *(_execute_one(tool_executor, call, config) for call in calls)
                )
            )
            return {"messages": tool_msgs}

        # 回退路径:通用执行器整体执行 + 节点级兜底
        try:
            return await tool_executor.ainvoke(state, config=config)
        except Exception as exc:  # noqa: BLE001 - 兜底所有工具异常
            return _error_messages(state, exc)

    return tools_node


async def _execute_one(executor: Any, call: dict[str, Any], config=None) -> ToolMessage:
    """执行单个 tool_call,失败只返回该调用的错误 ToolMessage。

    ``call`` 形如 ``{"name": ..., "args": ..., "id": ..., "type": "tool_call"}``;
    ``config`` 为节点级配置,透传给工具调用(run_id/callbacks 等,与 ToolNode 一致)。
    """
    name = call.get("name")
    call_id = call.get("id") or ""
    tool = executor.tools_by_name.get(name)
    if tool is None:
        return ToolMessage(
            content=f"[工具执行出错] 未知工具: {name}",
            tool_call_id=call_id,
            name=name,
        )
    try:
        result = await tool.ainvoke(call.get("args") or {}, config=config)
    except Exception as exc:  # noqa: BLE001 - 单 call 兜底
        return ToolMessage(
            content=f"[工具执行出错] {exc}",
            tool_call_id=call_id,
            name=name,
        )
    return ToolMessage(content=str(result), tool_call_id=call_id, name=name)


def _error_messages(state: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """把一次工具执行异常转成 ToolMessage 列表并入消息历史。"""
    messages = state.get("messages", [])
    # 找到最后一个带 tool_calls 的 AIMessage,用其 id 作为错误 ToolMessage 的归属
    error_content = f"[工具执行出错] {exc}"
    tool_msgs: list[ToolMessage] = []
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for call in msg.tool_calls:
                tool_msgs.append(
                    ToolMessage(
                        content=error_content,
                        tool_call_id=call.get("id") or "",
                        name=call.get("name"),
                    )
                )
            break
    if not tool_msgs:
        tool_msgs = [ToolMessage(content=error_content, tool_call_id="")]
    return {"messages": tool_msgs}
