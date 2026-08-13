"""OpenAI 兼容协议传输包:面向 deepseek / openai / ollama 等兼容端点的客户端。

- ``OpenAICompatClient``:直接构造 ``/chat/completions`` 请求体,
  ``reasoning_effort`` 原样上传,流式走自研 SSE 解析(``ai/protocol/sse.py``);
- 依赖 ``httpx``,框架无关:不 import langchain(编排桥接由组合根经
  ``ai/bridge/langchain.py`` 包装)。
"""

from codeagent.ai.transport.openai_compat import OpenAICompatClient

__all__ = ["OpenAICompatClient"]
