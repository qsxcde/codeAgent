"""模型运行时内的纯函数:model:effort 解析。"""

from __future__ import annotations

#: 合法思考强度白名单。
KNOWN_EFFORTS = ("low", "medium", "high")


def split_model_pattern(pattern: str) -> tuple[str, str | None]:
    """``deepseek-v4-pro:high`` → (``deepseek-v4-pro``, ``high``)。

    本函数是 model:effort 解析的**唯一实现**,避免多处复制漂移。
    """
    if ":" in pattern:
        base, effort = pattern.rsplit(":", 1)
        if effort in KNOWN_EFFORTS:
            return base, effort
    return pattern, None
