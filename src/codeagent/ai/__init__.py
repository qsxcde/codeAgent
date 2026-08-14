"""模型运行时(AI)包:供应商注册、模型目录与统一构造入口。

分层:
- ``providers``:各模型供应商工厂(provider 名 → 工厂);
- ``catalog``:模型目录(ModelSpec / ModelStore / ModelRegistry);
- ``protocol``:框架无关的消息模型与流式事件(ChatClient 协议);
- ``transport``:OpenAI 兼容协议传输实现;
- ``factory.create_llm``:按 provider + model 的统一构造入口(组合根消费;
  编排侧适配经组合根 ``ChatModelPort``,``ai/bridge`` 已随编排自研删除)。
"""

from codeagent.ai.factory import create_llm, get_available_providers

__all__ = ["create_llm", "get_available_providers"]
