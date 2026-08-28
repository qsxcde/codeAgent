"""Shared conservative shell tokenization for security and tool adapters."""

from __future__ import annotations

import shlex

SEGMENT_SEPARATORS = frozenset({"|", "&&", ";", "||", "&"})


def tokenize_shell(command: str) -> list[str] | None:
    """Tokenize shell syntax; return ``None`` when it cannot be trusted."""

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def split_segments(command: str) -> list[list[str]] | None:
    """Split a tokenized command at shell pipeline/control separators."""

    tokens = tokenize_shell(command)
    if tokens is None:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SEGMENT_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def last_segment_first_token(command: str) -> str:
    """Return the first executable token in the final shell segment."""

    segments = split_segments(command)
    if not segments:
        return ""
    for token in segments[-1]:
        if token:
            return token
    return ""


__all__ = [
    "SEGMENT_SEPARATORS",
    "last_segment_first_token",
    "split_segments",
    "tokenize_shell",
]
