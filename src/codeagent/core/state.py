"""编排层状态:AgentState。

ReAct 循环只需消息历史,故继承 LangGraph 的 ``MessagesState``
(其 ``messages`` 字段通过 ``add_messages`` 归约自动累加/合并)。
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """ReAct 循环的图状态:仅消息历史。

    ``add_messages`` 归约保证:同一 role 相邻消息自动合并、工具结果
    按 tool_call_id 归属到对应 AIMessage 之后。
    """

    messages: Annotated[list, add_messages]
