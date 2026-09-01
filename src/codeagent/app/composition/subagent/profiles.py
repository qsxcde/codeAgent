"""Tool allow-lists for the first Subagent runtime profile."""

from __future__ import annotations

from collections.abc import Collection

READ_ONLY_TOOL_NAMES = frozenset({"read", "grep", "find", "ls", "skill"})


def allowed_tool_names_for(profile: str) -> Collection[str]:
    """Return the composition-level tool allow-list for one profile."""
    if profile != "read_only":
        raise ValueError(f"unsupported Subagent profile: {profile}")
    return READ_ONLY_TOOL_NAMES


__all__ = ["READ_ONLY_TOOL_NAMES", "allowed_tool_names_for"]
