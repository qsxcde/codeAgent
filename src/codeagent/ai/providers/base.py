"""provider 注册和工厂的最小类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeAlias

from codeagent.ai.model.protocols import ChatClient

ProviderFactory: TypeAlias = Callable[..., ChatClient]


@dataclass(frozen=True)
class ProviderDefinition:
    """一个内置 provider 的显式注册描述。"""

    provider_id: str
    factory: ProviderFactory

    def create_client(self, **kwargs: Any) -> ChatClient:
        return self.factory(**kwargs)
