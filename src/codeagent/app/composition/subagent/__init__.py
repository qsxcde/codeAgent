"""Subagent runtime adapters owned by the application composition root."""

from .delegate_tool import DelegateTool
from .factory import create_serial_subagent_runner
from .profiles import (
    READ_ONLY_TOOL_NAMES,
    SubagentProfile,
    allowed_tool_names_for,
    instructions_for,
    profile_for,
)
from .runner import SerialSubagentRunner

__all__ = [
    "DelegateTool",
    "READ_ONLY_TOOL_NAMES",
    "SubagentProfile",
    "SerialSubagentRunner",
    "allowed_tool_names_for",
    "create_serial_subagent_runner",
    "instructions_for",
    "profile_for",
]
