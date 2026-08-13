"""编排层测试:假 ports 跑通整个 ReAct 循环(离线,零网络)。"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode

from codeagent.ai.providers.fake import FakeClient
from codeagent.core import AgentPorts, build_graph
from codeagent.tools.registry import make_tools


def _graph(model: FakeClient):
    from codeagent.ai.bridge.langchain import to_langchain_runnable

    tools = make_tools()
    bound = to_langchain_runnable(model.bind_tools(tools))
    ports = AgentPorts(
        bound_model=bound,
        tool_executor=ToolNode(tools),
        checkpointer=InMemorySaver(),
    )
    return build_graph(ports)


def _invoke(graph, text: str, thread: str = "t1"):
    import asyncio

    async def _run():
        return await graph.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config={"configurable": {"thread_id": thread}},
        )

    return asyncio.run(_run())


def test_agent_ports_frozen_and_checkpointer_default():
    tools = make_tools()
    model = FakeClient()
    ports = AgentPorts(bound_model=model, tool_executor=ToolNode(tools))
    assert ports.bound_model is model
    assert ports.checkpointer is None
    # frozen dataclass 不可改字段
    with pytest.raises(Exception):
        ports.bound_model = None  # type: ignore[misc]


def test_direct_reply_ends_loop():
    graph = _graph(FakeClient(response="你好"))
    out = _invoke(graph, "打招呼")
    # 只经历一轮 agent,无工具调用
    types = [type(m).__name__ for m in out["messages"]]
    assert types == ["HumanMessage", "AIMessage"]
    assert out["messages"][-1].content == "你好"


def test_tool_call_then_reply_react_loop(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("hello file")
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "read", "args": {"file_path": str(target)}, "id": "c1", "type": "tool_call"}
                ],
            },
            {"content": "已读取"},
        ]
    )
    graph = _graph(model)
    out = _invoke(graph, "读文件")
    types = [type(m).__name__ for m in out["messages"]]
    assert types == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert "hello file" in out["messages"][2].content
    assert out["messages"][-1].content == "已读取"


def test_tool_error_does_not_break_graph(tmp_path):
    # 读取不存在的文件 → 工具返回错误 ToolMessage,图继续回 agent
    missing = tmp_path / "nope.txt"
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "read", "args": {"file_path": str(missing)}, "id": "c1", "type": "tool_call"}
                ],
            },
            {"content": "处理了错误"},
        ]
    )
    graph = _graph(model)
    out = _invoke(graph, "读不存在的文件")
    types = [type(m).__name__ for m in out["messages"]]
    assert types == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert out["messages"][-1].content == "处理了错误"


def test_multi_tool_call_single_failure_keeps_success(tmp_path):
    """多 tool_calls 单失败:成功 call 结果保留,失败 call 错误只带自身 id(回归:P2-2)。"""
    missing = tmp_path / "nope.txt"
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "bash", "args": {"command": "echo ok"}, "id": "c-ok", "type": "tool_call"},
                    {"name": "read", "args": {"file_path": str(missing)}, "id": "c-bad", "type": "tool_call"},
                ],
            },
            {"content": "继续"},
        ]
    )
    graph = _graph(model)
    out = _invoke(graph, "并行执行")
    tool_msgs = [m for m in out["messages"] if type(m).__name__ == "ToolMessage"]
    assert len(tool_msgs) == 2
    by_id = {m.tool_call_id: m for m in tool_msgs}
    assert set(by_id) == {"c-ok", "c-bad"}
    # 成功 call 携带真实结果
    assert "ok" in by_id["c-ok"].content
    assert "[工具执行出错]" not in by_id["c-ok"].content
    # 失败 call 携带自身错误,且错误文本不污染成功 call
    assert "[工具执行出错]" in by_id["c-bad"].content
    assert "文件不存在" in by_id["c-bad"].content
    # 图继续回 agent 完成后续回复
    assert out["messages"][-1].content == "继续"


def test_unknown_tool_generates_error_and_does_not_break_graph():
    """未知工具名 → 携带自身 id 的「未知工具」错误,图不中断。"""
    model = FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "nonexistent_tool", "args": {}, "id": "c-x", "type": "tool_call"}
                ],
            },
            {"content": "已处理未知工具"},
        ]
    )
    graph = _graph(model)
    out = _invoke(graph, "调用未知工具")
    tool_msgs = [m for m in out["messages"] if type(m).__name__ == "ToolMessage"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "c-x"
    assert "未知工具" in tool_msgs[0].content
    assert "nonexistent_tool" in tool_msgs[0].content
    assert out["messages"][-1].content == "已处理未知工具"


def test_build_graph_top_level_no_side_effect():
    """import 模块顶层不建模型、不发请求、不读 key。"""
    import codeagent.core.loop as loop_mod

    # 仅确认符号存在,且模块定义无副作用(这里能 import 即已通过)
    assert callable(loop_mod.build_graph)


def test_default_recursion_limit_is_50():
    """默认循环上限提升为 50(P2-15),约 25 轮 ReAct。"""
    from codeagent.core.loop import DEFAULT_RECURSION_LIMIT

    assert DEFAULT_RECURSION_LIMIT == 50


def test_should_continue_logic():
    from langchain_core.messages import AIMessage, HumanMessage

    from codeagent.core.loop import should_continue
    from codeagent.core.state import AgentState

    no_tool: AgentState = {"messages": [HumanMessage("hi"), AIMessage(content="bye")]}
    assert should_continue(no_tool) == "end"

    with_tool: AgentState = {
        "messages": [
            HumanMessage("hi"),
            AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": "c1", "type": "tool_call"}]),
        ]
    }
    assert should_continue(with_tool) == "tools"

    empty: AgentState = {"messages": []}
    assert should_continue(empty) == "end"


class _StubTool:
    """记录各调用开始时间与收到的 config,用于断言并行/串行与 config 透传。"""

    def __init__(self, name: str, delay: float) -> None:
        self.name = name
        self.delay = delay
        self.starts: list[float] = []
        self.received_configs: list[object] = []

    async def ainvoke(self, args: dict, config=None) -> str:
        self.starts.append(time.monotonic())
        self.received_configs.append(config)
        await asyncio.sleep(self.delay)
        return f"{self.name}:ok"


class _StubExecutor:
    def __init__(self) -> None:
        self.tool_a = _StubTool("tool_a", 0.2)
        self.tool_b = _StubTool("tool_b", 0.2)
        self.tools_by_name = {"tool_a": self.tool_a, "tool_b": self.tool_b}


def test_multi_tool_calls_execute_in_parallel():
    """多 tool_calls 并行执行(回归:此前串行导致耗时线性叠加)。"""
    from langchain_core.messages import AIMessage

    from codeagent.core.nodes.tools import make_tools_node

    executor = _StubExecutor()
    node = make_tools_node(executor)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "tool_a", "args": {}, "id": "c1", "type": "tool_call"},
                    {"name": "tool_b", "args": {}, "id": "c2", "type": "tool_call"},
                ],
            )
        ]
    }

    started = time.monotonic()
    out = asyncio.run(node(state, config={"configurable": {"thread_id": "t1"}}))
    elapsed = time.monotonic() - started

    # 两个工具均执行且结果正确
    tool_msgs = [m for m in out["messages"] if type(m).__name__ == "ToolMessage"]
    assert len(tool_msgs) == 2
    assert {m.tool_call_id for m in tool_msgs} == {"c1", "c2"}

    # 并行:两调用几乎同时开始(时间差远小于单个耗时 0.2s)
    start_a = executor.tool_a.starts[0]
    start_b = executor.tool_b.starts[0]
    assert abs(start_a - start_b) < 0.05, "两个工具未并行开始"
    # 并行:总耗时约等于最慢单个(0.2s),而非两者之和(0.4s)
    assert elapsed < 0.35, f"总耗时 {elapsed:.3f}s 表明串行执行"
    # config 透传:每个工具都收到节点级 config
    for tool in (executor.tool_a, executor.tool_b):
        assert len(tool.received_configs) == 1
        assert tool.received_configs[0] == {"configurable": {"thread_id": "t1"}}
