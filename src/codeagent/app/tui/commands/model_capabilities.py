"""TUI 模型能力诊断文本。"""

from __future__ import annotations

from typing import Any


def append_model_capability_lines(
    lines: list[str], capabilities: Any, session: Any | None
) -> None:
    """追加当前模型的静态能力与运行期缓存观测。"""
    if capabilities is None:
        return
    window = (
        f"{capabilities.context_window:,}"
        if isinstance(capabilities.context_window, int)
        else "未知"
    )
    source = capabilities.window_source or "unknown"
    lines.extend(
        [
            "模型能力:",
            f"  上下文窗口: {window} · 来源 {source}",
            f"  思考: {_capability_label(capabilities.reasoning)}",
            f"  工具调用: {_capability_label(capabilities.tool_calling)}",
            "  " + _cache_capability_line(capabilities, session),
        ]
    )


def _capability_label(value: bool | None) -> str:
    if value is True:
        return "支持"
    if value is False:
        return "不支持"
    return "未知"


def _cache_capability_line(capabilities: Any, session: Any | None) -> str:
    observed = getattr(capabilities, "cached_tokens_observed", None)
    usage = getattr(session, "usage", None)
    if observed is None and usage is not None:
        has_usage = any(
            getattr(usage, name, 0)
            for name in (
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cached_tokens",
            )
        )
        if has_usage:
            observed = usage.cached_tokens
    if observed is None:
        observation = "观测未观测"
    elif observed > 0:
        observation = f"观测命中 {observed} token"
    else:
        observation = "观测未命中"
    return f"缓存能力: {_capability_label(capabilities.prompt_cache)} · {observation}"
