"""langchain 编排桥接包:把自研 ChatClient / ChatResponse 包装为 langchain 对象。

- ``to_langchain_ai_message``:ChatResponse → langchain AIMessage;
- ``to_langchain_runnable``:ChatClient → langchain Runnable(ainvoke / astream),
  供保留的 langgraph 编排层消费(见 bridge/langchain.py 与 design D5)。
"""

from codeagent.ai.bridge.langchain import to_langchain_ai_message, to_langchain_runnable

__all__ = ["to_langchain_ai_message", "to_langchain_runnable"]
