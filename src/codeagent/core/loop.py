"""ReAct 循环:build_graph 纯组装,零副作用。

模块顶层没有任何副作用(不建模型、不发请求、不读密钥),可被平台直接 import。
循环条件 `should_continue` 只看 state 形状(最后一条消息有没有 tool_calls),
不 import 任何具体工具。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from codeagent.core.nodes.agent import make_agent_node
from codeagent.core.nodes.tools import make_tools_node
from codeagent.core.ports import AgentPorts
from codeagent.core.state import AgentState

DEFAULT_RECURSION_LIMIT = 50


def should_continue(state: AgentState) -> str:
    """ReAct 循环条件:最后一条消息含 tool_calls → tools,否则结束。"""
    messages = state["messages"]
    if not messages:
        return "end"
    last = messages[-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "end"


def build_graph(
    ports: AgentPorts,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
) -> Any:
    """组装并编译 ReAct 循环图。

    - 拓扑:START → agent → (should_continue) → tools → agent / END;
    - checkpointer 由 ``ports.checkpointer`` 决定(None 则不持久化);
    - ``recursion_limit`` 防止模型无限循环调用工具。
    """
    agent = make_agent_node(ports.bound_model)
    tools = make_tools_node(ports.tool_executor)

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    g.add_edge("tools", "agent")

    # recursion_limit 是运行期 RunnableConfig 键,不在 compile 传入;
    # 由调用方(session)在 run config 中注入(见 session/session.py)。
    return g.compile(checkpointer=ports.checkpointer)
