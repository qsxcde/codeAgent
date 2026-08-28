"""Session-level error presentation policy."""

from __future__ import annotations

import asyncio

from codeagent.core.errors import ContextPreparationError
from codeagent.core.loop import RecursionLimitError
from codeagent.session.runtime.state import RunPhase, RuntimeFailure


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
    code = "runtime_error"
    cause_type = type(exc).__name__
    if isinstance(exc, ContextPreparationError):
        # Budget/context failures are deterministic pre-model failures.  They
        # must not be presented as retryable provider errors, and the cause
        # remains visible for diagnostics.
        code = exc.code
        phase_value = exc.phase
        cause_type = type(exc.cause).__name__
        if hasattr(exc, "result"):
            result = exc.result
            snapshot = result.snapshot
            budget_status = result.status
            input_tokens = snapshot.input_tokens
            input_budget = snapshot.input_budget
            headroom = snapshot.headroom
            window_source = snapshot.window_source
        else:
            budget_status = None
            input_tokens = None
            input_budget = None
            headroom = None
            window_source = None
    elif isinstance(exc, RecursionLimitError):
        code = "recursion_limit"
    elif phase_value == "tool_running":
        code = "tool_error"
    elif phase_value == "awaiting_confirmation":
        code = "confirmation_error"
    elif phase_value == "persistence":
        code = "persistence_error"
    elif phase_value == "compaction":
        code = "compaction_failed"
    else:
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a project dependency
            httpx = None
        if httpx is not None and isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403):
                code = "model_auth"
            elif status == 429:
                code = "model_rate_limit"
            elif status == 404:
                code = "model_protocol"
            else:
                code = "model_network"
        elif httpx is not None and isinstance(exc, httpx.TimeoutException):
            code = "model_timeout" if phase_value == RunPhase.MODEL_WAIT.value else "runtime_timeout"
        elif httpx is not None and isinstance(exc, httpx.ConnectError):
            code = "model_network"
        elif isinstance(exc, asyncio.CancelledError):
            code = "cancelled"
        elif phase_value == RunPhase.MODEL_WAIT.value:
            code = "model_error"

    if not isinstance(exc, ContextPreparationError):
        budget_status = None
        input_tokens = None
        input_budget = None
        headroom = None
        window_source = None

    retryable = (
        code
        in {
            "model_auth",
            "model_network",
            "model_timeout",
            "model_rate_limit",
            "model_error",
        }
        and side_effect_state == "none"
        and not cleanup_uncertain
    )
    return RuntimeFailure(
        code=code,
        message=friendly_error(exc) if isinstance(exc, Exception) else str(exc),
        phase=phase_value,
        retryable=retryable,
        side_effect_state=side_effect_state,
        cleanup_uncertain=cleanup_uncertain,
        operation_id=operation_id,
        cause_type=cause_type,
        budget_status=budget_status,
        input_tokens=input_tokens,
        input_budget=input_budget,
        headroom=headroom,
        window_source=window_source,
    )


def friendly_error(exc: Exception) -> str:
    """Return the existing user-facing session error message."""
    if isinstance(exc, RecursionLimitError):
        return exc.friendly
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a project dependency
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
