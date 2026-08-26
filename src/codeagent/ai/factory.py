"""旧模型工厂入口，保留为短期兼容 façade。

实际的 provider/model/effort 选择和客户端装配位于
``codeagent.app.composition.model_selection``；AI 层不再承载应用装配逻辑。
"""

import importlib


def _split_pattern(model: str) -> tuple[str, str | None]:
    """兼容旧的内部测试和调用方。"""
    return getattr(_composition(), "split_model_pattern")(model)


def _composition():
    """延迟解析组合根，避免 AI 包导入时建立反向静态依赖。"""
    return importlib.import_module("codeagent.app.composition.model_selection")


def __getattr__(name: str):
    if name in {"create_llm", "get_available_providers", "split_model_pattern"}:
        return getattr(_composition(), name)
    raise AttributeError(name)


__all__ = ["_split_pattern", "create_llm", "get_available_providers"]
