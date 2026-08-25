"""Compatibility facade for session storage backends and models."""

from codeagent.session.json_file_store import JsonFileStore
from codeagent.session.memory_store import MemoryStore
from codeagent.session.store_codec import TITLE_MAX
from codeagent.session.store_models import (
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
