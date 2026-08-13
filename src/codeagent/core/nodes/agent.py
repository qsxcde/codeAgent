"""agent 节点:调用已 bind 工具的模型,产出下一轮回复。

节点保持"纯函数"——输入消息历史,输出含完整 AIMessage 的 state 更新。
节点经 ``astream`` 消费模型增量并聚合为单一完整消息写回(激活流式路径,
H4:ainvoke 只取整块,astream 此前是死代码);token 级增量由桥接层产出,
聚合后由 add_messages 归约为一条消息。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage

from codeagent.core.state import AgentState

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def make_agent_node(bound_model: BaseChatModel) -> Any:
    """返回一个 ReAct agent 节点。

    - 节点读取 state 的 ``messages``,用 ``bound_model.astream`` 逐增量消费并
      累加合并(AIMessageChunk.__add__),最终返回单一完整 ``AIMessage``;
    - 返回 ``{"messages": [AIMessage]}`` 并入图状态(由 add_messages 归约)。
    - 该节点为异步实现(内部 await),LangGraph 会用默认线程执行。
    """

    async def agent_node(state: AgentState, config=None) -> dict[str, Any]:
        acc = None
        async for chunk in bound_model.astream(state["messages"], config=config):
            acc = chunk if acc is None else acc + chunk
        if acc is None:
            # 流式未产出任何块(空响应)时给空消息兜底
            acc = AIMessage(content="")
        if not isinstance(acc, AIMessage):
            # 容错:某些模型可能返回 BaseMessage 的其它子类
            acc = AIMessage(content=acc.content)
        return {"messages": [acc]}

    return agent_node
