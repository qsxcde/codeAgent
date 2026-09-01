"""Allow-list and size limits for serialized Subagent result values."""

from __future__ import annotations

import json
from typing import Any

MAX_RESULT_BYTES = 64_000
MAX_FINDINGS = 16
MAX_EVIDENCE = 32
_DROP_RESULT_KEYS = frozenset(
    {"prompt", "context", "history", "messages", "transcript", "raw", "tool_output"}
)


def bounded_result(value: Any) -> dict[str, Any]:
    """Keep only result facts that are safe and useful after a restart."""
    if not isinstance(value, dict):
        return {}
    result = {
        key: _result_value(key, value[key])
        for key in ("summary", "failure", "findings", "evidence", "usage", "artifact", "cleanup_uncertain")
        if key in value and key not in _DROP_RESULT_KEYS
    }
    while _json_size(result) > MAX_RESULT_BYTES:
        if result.get("evidence"):
            result["evidence"].pop()
        elif result.get("findings"):
            result["findings"].pop()
        elif len(result.get("summary", "")) > 1_000:
            result["summary"] = result["summary"][:1_000]
        else:
            break
    return result


def _result_value(key: str, value: Any) -> Any:
    if key == "summary":
        return _text(value, 16_000)
    if key == "failure":
        return _failure(value)
    if key == "findings":
        return _items(value, MAX_FINDINGS, _finding)
    if key == "evidence":
        return _items(value, MAX_EVIDENCE, _evidence)
    if key == "usage":
        return _usage(value)
    if key == "artifact":
        return _artifact(value)
    return bool(value)


def _failure(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("reason_code", "message", "error", "error_message", "phase", "side_effect_state"):
        if value.get(key) is not None:
            result[key] = _text(value[key], 64 if key == "phase" else 2_000)
    for key in ("retryable", "cleanup_uncertain"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    return result


def _finding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    ids = value.get("evidence_ids", ())
    if not isinstance(ids, (list, tuple)):
        ids = ()
    return {
        "summary": _text(value.get("summary"), 2_000),
        "evidence_ids": [_text(item, 128) for item in ids[:32]],
    }


def _evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, limit in (
        ("evidence_id", 128), ("source", 512), ("summary", 2_000),
        ("locator", 512), ("excerpt", 1_200), ("completeness", 32), ("continuation", 512),
    ):
        if value.get(key) is not None:
            result[key] = _text(value[key], limit)
    return result


def _usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens"):
        try:
            result[key] = max(0, int(value.get(key, 0) or 0))
        except (TypeError, ValueError):
            result[key] = 0
    return result


def _artifact(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: _text(value.get(key), limit)
        for key, limit in (("ref", 512), ("kind", 128), ("label", 200))
        if value.get(key) is not None
    }


def _items(value: Any, limit: int, mapper: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [mapped for item in value[:limit] if (mapped := mapper(item))]


def _text(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


__all__ = ["bounded_result"]
