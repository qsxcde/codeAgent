"""Errors raised by the in-memory Agent Runtime."""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentContinueError",
    "AgentRuntimeError",
    "ContextPreparationError",
    "ContextPreflightError",
    "ContextTransformTimeoutError",
    "SubagentContractError",
    "SubagentRequestError",
    "SubagentStateError",
]


class AgentRuntimeError(RuntimeError):
    """Base error for failures owned by the Agent Runtime."""


class SubagentContractError(AgentRuntimeError, ValueError):
    """Base error for invalid provider-neutral Subagent values."""

    code = "subagent_contract_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(message)


class SubagentRequestError(SubagentContractError):
    """A Subagent request cannot be admitted as constructed."""

    code = "invalid_request"


class SubagentStateError(SubagentContractError):
    """A Subagent lifecycle transition violates its state contract."""

    code = "invalid_subagent_transition"


class AgentContinueError(AgentRuntimeError, ValueError):
    """The current context cannot be resumed as an Agent turn."""


class ContextPreparationError(AgentRuntimeError, ValueError):
    """A budget or context extension failed before the model request."""

    code = "context_preparation_failed"
    phase = "context_preparation"

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


class ContextTransformTimeoutError(ContextPreparationError):
    """A request-local context extension exceeded its configured timeout."""

    code = "context_transform_timeout"

    def __init__(self, extension: str, timeout: float) -> None:
        self.extension = extension
        self.timeout = timeout
        super().__init__(
            TimeoutError(
                f"{extension} exceeded context transform timeout of {timeout}s"
            )
        )


class ContextPreflightError(ContextPreparationError):
    """A deterministic local request block from the budget preflight."""

    phase = "context_preflight"

    def __init__(self, result: Any) -> None:
        self.result = result
        self.code = (
            "context_budget_exceeded"
            if result.status == "over_limit"
            else "context_budget_uncertain"
        )
        self.budget_status = result.status
        self.input_tokens = result.input_tokens
        self.input_budget = result.input_budget
        self.headroom = result.headroom
        self.window_source = result.window_source
        self.warning_boundary = result.warning_boundary
        super().__init__(ValueError(result.reason))
