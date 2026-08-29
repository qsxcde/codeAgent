"""Provider 调用失败的稳定分类与安全诊断信息。"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any, Literal, TypeAlias

import httpx


ProviderErrorKind: TypeAlias = Literal[
    "network",
    "timeout",
    "rate_limit",
    "authentication",
    "invalid_request",
    "unsupported_parameter",
    "server",
    "unknown",
]

_MAX_DETAIL_LENGTH = 1000
_UNSUPPORTED_PARAMETER = re.compile(
    r"(?:unsupported|unknown|unrecognized)\s+(?:parameter|field|argument|key)|"
    r"(?:does not support|not supported|unsupported).*",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_SENSITIVE_VALUE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|password|secret|token)[\"']?\s*[:=]\s*)"
    r"([\"']?[^\s,;\"'}]+[\"']?)"
)


class ProviderError(Exception):
    """可供上层处理的 Provider 错误。"""

    def __init__(
        self,
        *,
        kind: ProviderErrorKind,
        retryable: bool,
        detail: str,
        status_code: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code
        self.provider = provider
        self.model = model
        self.request_id = request_id
        self.retry_after = retry_after
        self.detail = _bounded_detail(detail)
        super().__init__(self._message())

    def _message(self) -> str:
        source = self.provider or "unknown provider"
        model = f" model={self.model}" if self.model else ""
        status = f" HTTP {self.status_code}" if self.status_code is not None else ""
        return f"Provider {source}{model} {self.kind} failure{status}: {self.detail}"


class ProviderHTTPError(httpx.HTTPStatusError, ProviderError):
    """带结构化分类、同时兼容 ``httpx.HTTPStatusError`` 的 HTTP 错误。"""

    def __init__(
        self,
        original: httpx.HTTPStatusError,
        *,
        kind: ProviderErrorKind,
        retryable: bool,
        detail: str,
        status_code: int | None,
        provider: str | None,
        model: str | None,
        request_id: str | None,
        retry_after: float | None,
    ) -> None:
        # HTTPStatusError.__init__ calls ``super().__init__(message)``. With
        # multiple inheritance that would resolve to ProviderError.__init__,
        # whose structured arguments are keyword-only, so initialize the
        # shared Exception state and HTTP compatibility attributes directly.
        Exception.__init__(self, "Provider HTTP request failed")
        self.request = original.request
        self.response = original.response
        ProviderError.__init__(
            self,
            kind=kind,
            retryable=retryable,
            detail=detail,
            status_code=status_code,
            provider=provider,
            model=model,
            request_id=request_id,
            retry_after=retry_after,
        )


def classify_provider_error(
    exc: BaseException,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ProviderError:
    """将底层 Provider 异常转换为稳定的项目错误。"""
    if isinstance(exc, ProviderError):
        return exc

    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status_code = _status_code(response)
        detail = _response_detail(response)
        kind, retryable = _http_classification(status_code, detail)
        return ProviderHTTPError(
            exc,
            kind=kind,
            retryable=retryable,
            detail=detail,
            status_code=status_code,
            provider=provider,
            model=model,
            request_id=_header(response, "x-request-id", "request-id"),
            retry_after=_retry_after(response),
        )

    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(
            kind="timeout",
            retryable=True,
            detail=_exception_detail(exc),
            provider=provider,
            model=model,
        )

    if isinstance(exc, httpx.TransportError):
        return ProviderError(
            kind="network",
            retryable=True,
            detail=_exception_detail(exc),
            provider=provider,
            model=model,
        )

    return ProviderError(
        kind="unknown",
        retryable=False,
        detail=_exception_detail(exc),
        provider=provider,
        model=model,
    )


def _http_classification(
    status_code: int | None,
    detail: str,
) -> tuple[ProviderErrorKind, bool]:
    if status_code == 401 or status_code == 403:
        return "authentication", False
    if status_code == 408:
        return "timeout", True
    if status_code == 429:
        return "rate_limit", True
    if status_code is not None and status_code >= 500:
        return "server", True
    if status_code in {400, 422} and _UNSUPPORTED_PARAMETER.search(detail):
        return "unsupported_parameter", False
    if status_code is not None and 400 <= status_code < 500:
        return "invalid_request", False
    return "unknown", False


def _response_detail(response: Any) -> str:
    payload: Any = None
    try:
        payload = response.json()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass

    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            for key in ("message", "detail"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return _bounded_detail(value)
            return _bounded_detail(_json_detail(error))
        if isinstance(error, str) and error.strip():
            return _bounded_detail(error)
        for key in ("message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _bounded_detail(value)
        if payload:
            return _bounded_detail(_json_detail(payload))

    try:
        text = response.text
    except (AttributeError, RuntimeError, TypeError, UnicodeDecodeError):
        text = ""
    return _bounded_detail(text) if isinstance(text, str) and text.strip() else "无响应详情"


def _json_detail(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def _bounded_detail(value: str) -> str:
    detail = _BEARER.sub("Bearer [REDACTED]", value.strip())
    detail = _SENSITIVE_VALUE.sub(r"\1[REDACTED]", detail)
    if len(detail) > _MAX_DETAIL_LENGTH:
        return f"{detail[:_MAX_DETAIL_LENGTH]}…"
    return detail or "无响应详情"


def _exception_detail(exc: BaseException) -> str:
    return _bounded_detail(str(exc) or exc.__class__.__name__)


def _status_code(response: Any) -> int | None:
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _header(response: Any, *names: str) -> str | None:
    headers = getattr(response, "headers", None)
    for name in names:
        try:
            value = headers.get(name) if headers is not None else None
        except (AttributeError, TypeError):
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _retry_after(response: Any) -> float | None:
    value = _header(response, "retry-after")
    if value is None:
        return None
    try:
        delay = float(value)
    except ValueError:
        return None
    return delay if math.isfinite(delay) and delay >= 0 else None


__all__ = ["ProviderError", "ProviderErrorKind", "ProviderHTTPError", "classify_provider_error"]
