"""Session-level error presentation policy."""

from __future__ import annotations

from codeagent.core.loop import RecursionLimitError


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
