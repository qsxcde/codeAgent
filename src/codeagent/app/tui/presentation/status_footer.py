"""底部状态栏的组合根装配数据。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FooterInfo:
    """状态栏装配数据(装配时解析固化, design D5)。"""

    model: str = ""
    effort: str = ""
    provider: str = ""
    cwd: str = ""
    #: app composition 提供的只读模型能力快照。
    capabilities: object | None = None


__all__ = ["FooterInfo"]
