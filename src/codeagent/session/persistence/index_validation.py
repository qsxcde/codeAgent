"""Validation helpers for rebuildable JSONL metadata indexes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def validate_index(
    data: object,
    path: Path,
    fingerprint: Callable[[Path], dict[str, int]],
) -> dict[str, Any] | None:
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    if not _valid_source(data.get("source"), fingerprint(path)):
        return None
    if not _valid_session(data.get("session")):
        return None
    if not _valid_meta(data.get("meta")):
        return None
    if not _valid_usage(data.get("usage")):
        return None
    if not _valid_compaction(data.get("lastCompaction")):
        return None
    return data


def _valid_source(source: object, expected: dict[str, int]) -> bool:
    return (
        isinstance(source, dict)
        and all(
            isinstance(source.get(key), int) and not isinstance(source.get(key), bool)
            for key in ("size", "mtime_ns", "ctime_ns")
        )
        and source == expected
    )


def _valid_session(session: object) -> bool:
    if not isinstance(session, dict):
        return False
    if not all(
        key in session and isinstance(session[key], str)
        for key in ("id", "timestamp", "cwd", "lastActivityAt", "model", "effort", "title")
    ):
        return False
    return (
        "parentSession" in session
        and isinstance(session["parentSession"], (str, type(None)))
        and type(session.get("archived")) is bool
    )


def _valid_meta(meta: object) -> bool:
    return (
        isinstance(meta, dict)
        and isinstance(meta.get("lastName"), str)
        and isinstance(meta.get("firstUserTitle"), str)
        and isinstance(meta.get("firstUserSeen"), bool)
    )


def _valid_usage(usage: object) -> bool:
    return isinstance(usage, dict) and all(
        isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
        for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")
    )


def _valid_compaction(compaction: object) -> bool:
    if compaction is None:
        return True
    if not isinstance(compaction, dict):
        return False
    return (
        all(key in compaction for key in ("id", "parentId", "firstKeptEntryId"))
        and isinstance(compaction["id"], str)
        and isinstance(compaction["firstKeptEntryId"], str)
        and isinstance(compaction["parentId"], (str, type(None)))
    )


__all__ = ["validate_index"]
