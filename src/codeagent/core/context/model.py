"""In-memory context owned by the Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from codeagent.core.contracts.errors import AgentContinueError
from codeagent.core.contracts.messages import Message
from codeagent.core.contracts.ports import AgentTool

__all__ = ["AgentContext"]


@dataclass
class AgentContext:
    """Mutable in-memory Agent context, independent of persistence."""

    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    tools: list[AgentTool] = field(default_factory=list)

    def copy(self) -> "AgentContext":
        """Copy the context containers without copying message/tool objects."""
        return AgentContext(
            system_prompt=self.system_prompt,
            messages=list(self.messages),
            tools=list(self.tools),
        )

    def validate_continue(self) -> None:
        """Ensure the context can continue without duplicating an assistant turn."""
        if not self.messages:
            raise AgentContinueError("cannot continue: context has no messages")
        if self.messages[-1].role == "assistant":
            raise AgentContinueError(
                "cannot continue from message role: assistant"
            )
