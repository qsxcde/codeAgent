"""Subagent runtime adapters owned by the application composition root."""

from .delegate_tool import DelegateTool
from .factory import create_serial_subagent_runner
from .profiles import (
    DEFAULT_PROFILE,
    READ_ONLY_TOOL_NAMES,
    SubagentProfile,
    allowed_tool_names_for,
    instructions_for,
    output_guidance_for,
    profile_names,
    profile_for,
    profile_error_message,
    prompt_for,
)
from .runner import SerialSubagentRunner

__all__ = [
    "DelegateTool",
    "DEFAULT_PROFILE",
    "READ_ONLY_TOOL_NAMES",
    "SubagentProfile",
    "SerialSubagentRunner",
    "allowed_tool_names_for",
    "create_serial_subagent_runner",
    "instructions_for",
    "output_guidance_for",
    "profile_names",
    "profile_for",
    "profile_error_message",
    "prompt_for",
]
