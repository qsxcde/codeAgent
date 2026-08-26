"""模型目录包:内置目录 ∪ models.json 的模型元数据与解析。

- ``ModelSpec``:模型元数据值对象(spec.py);
- ``ModelStore``:models.json 读写(store.py);
- ``ModelRegistry``:合并内置目录与用户覆盖,提供模型解析(registry.py);
- ``BUILTIN_CATALOGS``:内置模型目录(builtin.py)。
"""

from codeagent.ai.catalog.builtin import BUILTIN_CATALOGS
from codeagent.ai.catalog.registry import ModelRegistry
from codeagent.ai.catalog.spec import ModelSpec
from codeagent.ai.catalog.store import ModelStore

__all__ = ["BUILTIN_CATALOGS", "ModelRegistry", "ModelSpec", "ModelStore"]
