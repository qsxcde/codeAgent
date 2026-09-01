from __future__ import annotations

import importlib.util
from pathlib import Path


CORE_DIR = Path(__file__).parents[2] / "src" / "codeagent" / "core"

EXPECTED_FILES = {
    "agent.py",
    "contracts/__init__.py",
    "contracts/errors.py",
    "contracts/events.py",
    "contracts/messages.py",
    "contracts/ports.py",
    "contracts/subagent_state.py",
    "contracts/subagents.py",
    "context/__init__.py",
    "context/budget.py",
    "context/contracts.py",
    "context/model.py",
    "context/preflight.py",
    "execution/__init__.py",
    "execution/cleanup.py",
    "execution/result.py",
    "execution/runtime.py",
    "execution/state.py",
    "model/__init__.py",
    "model/request.py",
    "orchestration/__init__.py",
    "orchestration/batch.py",
    "orchestration/config.py",
    "orchestration/errors.py",
    "orchestration/loop.py",
    "orchestration/tool_call.py",
    "orchestration/turn.py",
    "support/__init__.py",
    "support/awaiting.py",
}

OLD_FLAT_MODULES = {
    "awaiting",
    "context_budget",
    "context_preflight",
    "errors",
    "events",
    "execution_cleanup",
    "execution_result",
    "execution_state",
    "loop",
    "loop_errors",
    "messages",
    "model_request",
    "ports",
    "tool_batch",
    "tool_result",
    "turn",
}


def test_core_modules_are_grouped_by_responsibility() -> None:
    actual_files = {
        path.relative_to(CORE_DIR).as_posix()
        for path in CORE_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    }

    assert EXPECTED_FILES <= actual_files


def test_old_flat_core_modules_are_not_compatibility_entries() -> None:
    for module_name in OLD_FLAT_MODULES:
        old_path = CORE_DIR / f"{module_name}.py"
        assert not old_path.exists(), old_path

        qualified_name = f"codeagent.core.{module_name}"
        try:
            module_spec = importlib.util.find_spec(qualified_name)
        except ModuleNotFoundError:
            module_spec = None
        assert module_spec is None, qualified_name


def test_core_facade_preserves_public_object_identity() -> None:
    import codeagent.core as public

    from codeagent.core.agent import Agent
    from codeagent.core.context.budget import ContextBudgetInput
    from codeagent.core.context.contracts import (
        ContextBudgetPort,
        ContextPreparationRequest,
        ContextPreparer,
        ContextToolDefinition,
    )
    from codeagent.core.context.model import AgentContext
    from codeagent.core.contracts.errors import AgentRuntimeError
    from codeagent.core.contracts.events import AgentEvent
    from codeagent.core.contracts.messages import Message
    from codeagent.core.contracts.ports import AgentTool, ModelPort
    from codeagent.core.contracts.subagent_state import SubagentState
    from codeagent.core.contracts.subagents import (
        SubagentRequest,
        SubagentResult,
        SubagentRunner,
        SubagentStatus,
    )
    from codeagent.core.execution.runtime import ToolExecutionRuntime
    from codeagent.core.orchestration.config import AgentLoopConfig

    expected = {
        "Agent": Agent,
        "AgentContext": AgentContext,
        "AgentLoopConfig": AgentLoopConfig,
        "AgentRuntimeError": AgentRuntimeError,
        "AgentEvent": AgentEvent,
        "AgentTool": AgentTool,
        "ContextBudgetInput": ContextBudgetInput,
        "ContextBudgetPort": ContextBudgetPort,
        "ContextPreparationRequest": ContextPreparationRequest,
        "ContextPreparer": ContextPreparer,
        "ContextToolDefinition": ContextToolDefinition,
        "Message": Message,
        "ModelPort": ModelPort,
        "ToolExecutionRuntime": ToolExecutionRuntime,
        "SubagentRequest": SubagentRequest,
        "SubagentResult": SubagentResult,
        "SubagentRunner": SubagentRunner,
        "SubagentState": SubagentState,
        "SubagentStatus": SubagentStatus,
    }

    assert all(name in public.__all__ for name in expected)
    for name, value in expected.items():
        assert getattr(public, name) is value
