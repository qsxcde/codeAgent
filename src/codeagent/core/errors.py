"""Errors raised by the in-memory Agent Runtime."""

from __future__ import annotations

__all__ = ["AgentContinueError", "AgentRuntimeError"]


class AgentRuntimeError(RuntimeError):
    """Base error for failures owned by the Agent Runtime."""


class AgentContinueError(AgentRuntimeError, ValueError):
    """The current context cannot be resumed as an Agent turn."""
