"""模型供应商包:每 provider 一个文件。

约定:每个 provider 模块暴露 ``PROVIDER_NAME`` 与 ``make_llm(cfg=None)``。
兼容:``from codeagent.ai.providers import FakeClient`` 可用(fake provider)。
``PROVIDERS`` 注册表在此汇总,供 ``ai/catalog/registry.py`` 与 ``ai/factory.py`` 消费。
"""

from typing import Callable

from . import deepseek, fake, glm, kimi, minimax, openai, qwen
from .fake import FakeClient

#: 供应商注册表:provider 名 → 构造工厂(create_llm 分发用)。
PROVIDERS: dict[str, Callable] = {
    deepseek.PROVIDER_NAME: deepseek.make_llm,
    openai.PROVIDER_NAME: openai.make_llm,
    qwen.PROVIDER_NAME: qwen.make_llm,
    glm.PROVIDER_NAME: glm.make_llm,
    kimi.PROVIDER_NAME: kimi.make_llm,
    minimax.PROVIDER_NAME: minimax.make_llm,
    fake.PROVIDER_NAME: fake.make_llm,
}

__all__ = ["deepseek", "fake", "glm", "kimi", "minimax", "openai", "qwen", "FakeClient", "PROVIDERS"]
