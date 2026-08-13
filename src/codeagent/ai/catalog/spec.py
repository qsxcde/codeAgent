"""模型规格:携带模型元数据(仿 Pi 的 Model)。

元数据(价格/上下文/reasoning/别名)靠静态目录提供,不依赖 `/models` 探测——
因为 `/models` 只返回 id。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    """单个模型的元数据(不可变、可哈希)。

    早期缺陷(H14):``aliases`` 是可变 ``list``,frozen dataclass 的 ``hash()``
    抛 ``unhashable type``,且可变字段可被外部 ``append`` 污染共享实例。
    现在内部恒为 ``tuple``,构造时接受 list 输入并转换。
    """

    id: str
    name: str = ""
    reasoning: bool = False
    max_tokens: int | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # 接受 list 输入,内部转为 tuple(frozen 下用 object.__setattr__)
        if not isinstance(self.aliases, tuple):
            object.__setattr__(self, "aliases", tuple(self.aliases))
