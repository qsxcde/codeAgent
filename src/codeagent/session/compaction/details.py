"""Compaction file-operation details."""

from __future__ import annotations

from codeagent.core.contracts.messages import Message


def extract_file_ops(messages: list[Message]) -> dict[str, list[str]]:
    """Extract read and modified file paths from tool calls in order."""
    ops: dict[str, list[str]] = {"readFiles": [], "modifiedFiles": []}
    seen: dict[str, set[str]] = {"readFiles": set(), "modifiedFiles": set()}
    for message in messages:
        for call in message.tool_calls:
            path = str(call.args.get("file_path") or "")
            if not path:
                continue
            if call.name == "read":
                bucket = "readFiles"
            elif call.name in ("write", "edit"):
                bucket = "modifiedFiles"
            else:
                continue
            if path not in seen[bucket]:
                seen[bucket].add(path)
                ops[bucket].append(path)
    return ops
