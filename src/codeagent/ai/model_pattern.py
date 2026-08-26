"""旧模型选择语法入口，保留为兼容 re-export。"""

import importlib


def __getattr__(name: str):
    if name in {"KNOWN_EFFORTS", "split_model_pattern"}:
        module = importlib.import_module("codeagent.app.composition.model_selection")
        return getattr(module, name)
    raise AttributeError(name)


__all__ = ["KNOWN_EFFORTS", "split_model_pattern"]
