"""Runtime failure classification and user-facing error messages."""

from __future__ import annotations

import asyncio

from codeagent.core.contracts.errors import ContextPreparationError
from codeagent.core.orchestration.loop import RecursionLimitError
from codeagent.session.runtime.state import RunPhase, RuntimeFailure

_PROVIDER_ERROR_CODES = {
    "network": "model_network",
    "timeout": "model_timeout",
    "rate_limit": "model_rate_limit",
    "authentication": "model_auth",
    "invalid_request": "model_invalid_request",
    "unsupported_parameter": "model_unsupported_parameter",
    "server": "model_server",
    "unknown": "model_error",
}


def classify_error(
    exc: BaseException,
    *,
    phase: RunPhase | str,
    side_effect_state: str = "none",
    cleanup_uncertain: bool = False,
    operation_id: str | None = None,
) -> RuntimeFailure:
    """Map an exception to a stable, machine-readable runtime failure."""
    phase_value = phase.value if isinstance(phase, RunPhase) else str(phase)
    code = _error_code(exc, phase_value)
    budget = _budget_metadata(exc)
    provider_retryable = (
        _provider_retryable(exc)
        if phase_value == RunPhase.MODEL_WAIT.value
        else None
    )
    retryable = (
        provider_retryable
        if provider_retryable is not None
        else code
        in {"model_auth", "model_network", "model_timeout", "model_rate_limit", "model_error"}
    ) and side_effect_state == "none" and not cleanup_uncertain
    return RuntimeFailure(
        code=code,
        message=friendly_error(exc) if isinstance(exc, Exception) else str(exc),
        phase=budget.get("phase") or phase_value,
        retryable=retryable,
        side_effect_state=side_effect_state,
        cleanup_uncertain=cleanup_uncertain,
        operation_id=operation_id,
        cause_type=budget["cause_type"],
        budget_status=budget["budget_status"],
        input_tokens=budget["input_tokens"],
        input_budget=budget["input_budget"],
        headroom=budget["headroom"],
        window_source=budget["window_source"],
    )


def _error_code(exc: BaseException, phase: str) -> str:
    if isinstance(exc, ContextPreparationError):
        return exc.code
    if isinstance(exc, RecursionLimitError):
        return "recursion_limit"
    if phase == "tool_running":
        return "tool_error"
    if phase == "awaiting_confirmation":
        return "confirmation_error"
    if phase == "persistence":
        return "persistence_error"
    if phase == "compaction":
        return "compaction_failed"
    provider_kind = _provider_kind(exc)
    if provider_kind is not None and phase == RunPhase.MODEL_WAIT.value:
        return _PROVIDER_ERROR_CODES[provider_kind]
    try:
        import httpx
    except ImportError:  # pragma: no cover - project dependency
        httpx = None
    if httpx is not None and isinstance(exc, httpx.HTTPStatusError):
        return {
            401: "model_auth",
            403: "model_auth",
            429: "model_rate_limit",
            404: "model_protocol",
        }.get(exc.response.status_code, "model_network")
    if httpx is not None and isinstance(exc, httpx.TimeoutException):
        return "model_timeout" if phase == RunPhase.MODEL_WAIT.value else "runtime_timeout"
    if httpx is not None and isinstance(exc, httpx.ConnectError):
        return "model_network"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    return "model_error" if phase == RunPhase.MODEL_WAIT.value else "runtime_error"


def _provider_kind(exc: BaseException) -> str | None:
    """Read the AI error contract without making session depend on ``ai``."""
    kind = getattr(exc, "kind", None)
    return kind if isinstance(kind, str) and kind in _PROVIDER_ERROR_CODES else None


def _provider_retryable(exc: BaseException) -> bool | None:
    if _provider_kind(exc) is None:
        return None
    value = getattr(exc, "retryable", False)
    return value if isinstance(value, bool) else False


def _budget_metadata(exc: BaseException) -> dict[str, object]:
    default = {
        "phase": None,
        "cause_type": type(exc).__name__,
        "budget_status": None,
        "input_tokens": None,
        "input_budget": None,
        "headroom": None,
        "window_source": None,
    }
    if not isinstance(exc, ContextPreparationError):
        return default
    result = getattr(exc, "result", None)
    if result is None:
        return {
            **default,
            "phase": exc.phase,
            "cause_type": type(exc.cause).__name__,
        }
    snapshot = result.snapshot
    return {
        "phase": exc.phase,
        "cause_type": type(exc.cause).__name__,
        "budget_status": result.status,
        "input_tokens": snapshot.input_tokens,
        "input_budget": snapshot.input_budget,
        "headroom": snapshot.headroom,
        "window_source": snapshot.window_source,
    }


def friendly_error(exc: Exception) -> str:
    """Return the existing user-facing session error message."""
    if isinstance(exc, RecursionLimitError):
        return exc.friendly
    provider_kind = _provider_kind(exc)
    if provider_kind is not None:
        detail = str(getattr(exc, "detail", exc))
        labels = {
            "authentication": "认证失败",
            "rate_limit": "请求过于频繁",
            "timeout": "请求超时",
            "network": "无法连接模型服务",
            "server": "模型服务暂时不可用",
            "invalid_request": "模型请求无效",
            "unsupported_parameter": "模型不支持请求参数",
            "unknown": "模型请求失败",
        }
        status = getattr(exc, "status_code", None)
        suffix = f"(HTTP {status})" if isinstance(status, int) else ""
        return f"{labels[provider_kind]}{suffix}:{detail}"
    try:
        import httpx
    except ImportError:  # pragma: no cover - project dependency
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return (
                "认证失败(HTTP {status}):API Key 无效或未配置,"
                "请检查 .env / ~/.codeagent 配置,或在 TUI 中使用 /login 配置密钥"
            )
        if status == 404:
            return f"模型或端点不存在(HTTP {status}):请检查 provider/model 配置"
        if status == 429:
            return "请求过于频繁(HTTP 429),请稍后重试"
        return f"模型服务请求失败(HTTP {status}):{exc}"
    if isinstance(exc, httpx.TimeoutException):
        return "请求超时,请稍后重试(思考强度过高或网络不稳定)"
    if isinstance(exc, httpx.ConnectError):
        return "无法连接模型服务:请检查网络或 base_url 配置"
    return str(exc)


__all__ = ["classify_error", "friendly_error"]
