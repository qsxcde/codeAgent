"""Compaction file-operation details."""

from __future__ import annotations

from codeagent.core.messages import Message


def extract_file_ops(messages: list[Message]) -> dict[str, list[str]]:
    """Extract read and modified file paths from tool calls in order."""
    ops: dict[str, list[str]] = {"readFiles": [], "modifiedFiles": []}
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
            if path not in ops[bucket]:
                ops[bucket].append(path)
    return ops
