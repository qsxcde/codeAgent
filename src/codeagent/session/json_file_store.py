"""Compatibility facade for the JSONL session store."""

from codeagent.session.persistence.jsonl_store import JsonFileStore, _lock_for

__all__ = ["JsonFileStore"]
