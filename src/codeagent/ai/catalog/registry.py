"""模型注册表:内置目录 ∪ models.json(按 id upsert)+ 模型解析。

对应 Pi 的 ModelRegistry(解析)层:
- `ModelRegistry.resolve()` 把模型名解析成 `ModelSpec`;
- 供应商工厂注册表 ``PROVIDERS`` 与统一构造入口 ``create_llm`` 见
  ``codeagent.ai.factory``;``available_providers`` 的并集计算也在 factory
  (catalog 层不依赖 providers 层)。
"""

from __future__ import annotations

from codeagent.ai.catalog.builtin import BUILTIN_CATALOGS
from codeagent.ai.catalog.spec import ModelSpec
from codeagent.ai.catalog.store import ModelStore


class ModelRegistry:
    """合并内置目录与 models.json,提供模型解析。"""

    def __init__(self, store: ModelStore | None = None):
        # ModelSpec 为不可变值对象(frozen + tuple aliases),dict 浅拷贝即隔离;
        # 各 provider 目录字典独立,跨实例不共享可变状态(H14)。
        self._catalogs: dict[str, dict[str, ModelSpec]] = {
            name: dict(cat) for name, cat in BUILTIN_CATALOGS.items()
        }
        self._apply_user_overrides(store or ModelStore())

    def _apply_user_overrides(self, store: ModelStore) -> None:
        """Pi 的 upsert 语义:id 相同→覆盖,id 新→追加,内置保留。"""
        for provider, conf in store.load().items():
            base = self._catalogs.setdefault(provider, {})
            base.update({m.id: m for m in conf.get("models", [])})

    def available(self, provider: str) -> dict[str, ModelSpec]:
        # 返回副本:外部写入不持久化进注册表内部状态(H15)
        return dict(self._catalogs.get(provider, {}))

    def catalog_providers(self) -> list[str]:
        """模型目录中出现的 provider key(内置 ∪ models.json)。

        "可构造 provider"的并集计算在 ``ai/factory.get_available_providers``
        (目录 key ∪ 工厂 key),保持本层不依赖 providers。
        """
        return list(self._catalogs)

    def resolve(self, pattern: str, provider: str | None = None) -> ModelSpec:
        """解析模型名:两遍法——先全部精确 id,再全部别名(M12)。

        早期缺陷:按 provider 逐个"精确→别名"循环,使前序 provider 的别名优先于
        后续 provider 的精确 id;两遍法消除该顺序依赖。
        """
        candidates = [provider] if provider else list(self._catalogs)
        # 第一遍:全部精确 id
        for p in candidates:
            cat = self._catalogs.get(p, {})
            if pattern in cat:
                return cat[pattern]
        # 第二遍:全部别名
        for p in candidates:
            for spec in self._catalogs.get(p, {}).values():
                if pattern in spec.aliases:
                    return spec
        # 错误文案列出可用 model id(而非仅 provider 名)
        all_ids = sorted(m for cat in self._catalogs.values() for m in cat)
        raise ValueError(f"未找到模型 {pattern!r},可用模型: {all_ids}")
