"""Compatibility facade for session storage backends and models."""

from codeagent.session.persistence.codec import TITLE_MAX
from codeagent.session.persistence.jsonl_store import JsonFileStore
from codeagent.session.persistence.memory_store import MemoryStore
from codeagent.session.persistence.models import (
    CURRENT_VERSION,
    CompactionEntry,
    CompactionState,
    SessionRef,
    SessionStore,
    UsageStats,
)

__all__ = [
    "CURRENT_VERSION",
    "CompactionEntry",
    "CompactionState",
    "JsonFileStore",
    "MemoryStore",
    "SessionRef",
    "SessionStore",
    "TITLE_MAX",
    "UsageStats",
]
