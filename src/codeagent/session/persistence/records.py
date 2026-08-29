"""Typed shapes for the records stored in the session JSONL stream."""

from __future__ import annotations

from typing import Any, TypedDict


class SessionHeaderRecord(TypedDict, total=False):
    type: str
    version: int
    id: str
    parentSession: str | None
    timestamp: str
    cwd: str
    lastActivityAt: str


class MessageRecord(TypedDict, total=False):
    type: str
    id: str
    parentId: str | None
    role: str
    content: str
    timestamp: str
    tool_calls: list[dict[str, Any]]
    tool_call_id: str
    tool_output: dict[str, Any]


class MetadataRecord(TypedDict):
    type: str
    key: str
    value: Any
    timestamp: str


class UsageRecord(TypedDict):
    type: str
    timestamp: str
    input: int
    output: int
    reasoning: int
    cached: int


class ModelChangeRecord(TypedDict, total=False):
    type: str
    timestamp: str
    model: str
    effort: str


class CompactionRecord(TypedDict):
    type: str
    id: str
    parentId: str | None
    firstKeptEntryId: str
    timestamp: str
    summary: str
    details: dict[str, Any]


__all__ = [
    "CompactionRecord",
    "MessageRecord",
    "MetadataRecord",
    "ModelChangeRecord",
    "SessionHeaderRecord",
    "UsageRecord",
]
