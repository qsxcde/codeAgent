"""工具层安全决策类型。"""

from __future__ import annotations

from dataclasses import dataclass

ALLOW = "allow"
ASK = "ask"
DENY = "deny"


@dataclass(frozen=True)
class SecurityDecision:
    """工具层安全决策，与 core 的策略端口保持结构隔离。"""

    action: str
    reason: str = ""
    warning: bool = False


__all__ = ["ALLOW", "ASK", "DENY", "SecurityDecision"]
