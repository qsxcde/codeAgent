"""编排层:端口、事件、消息、循环(自研版,2026-08-14)。

分层约束:core 不 import config / ai / tools / session,仅依赖标准库与
本包内部模块。外部世界通过 AgentLoopConfig 注入模型、工具和运行时。
"""

from codeagent.core.context.model import AgentContext
from codeagent.core.context.budget import (
    ContextBudgetInput,
    ContextBudgetSnapshot,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_OUTPUT_RESERVE,
    DEFAULT_RESERVE_TOKENS,
    estimate_context_budget,
    govern_tool_messages,
)
from codeagent.core.context.diagnostics import ContextDiagnostics
from codeagent.core.context.preflight import (
    ContextPreflightConfig,
    ContextPreflightResult,
    PreflightStatus,
    evaluate_context_preflight,
)
from codeagent.core.context.contracts import (
    ContextBudgetPort,
    ContextPreparationRequest,
    ContextPreparer,
    ContextTransformer,
    ContextToolDefinition,
    TransformContext,
)
from codeagent.core.agent import Agent
from codeagent.core.contracts.errors import (
    AgentContinueError,
    AgentRuntimeError,
    ContextPreparationError,
    ContextPreflightError,
    ContextTransformTimeoutError,
)
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.hooks import (
    HookDiagnostic,
    HookFailureStage,
    HookPhase,
    HookScope,
    LifecycleHook,
    LifecycleHookEvent,
    classify_core_event,
    classify_session_event,
    core_event_scope_phase,
    hook_name,
    make_hook_diagnostic,
    session_event_phase,
    to_lifecycle_hook_event,
)
from codeagent.core.execution.runtime import (
    CleanupResult,
    OperationRegistry,
    ToolExecutionRuntime,
    ToolOperation,
)
from codeagent.core.orchestration.loop import (
    DEFAULT_RECURSION_LIMIT,
    RecursionLimitError,
    run_agent_loop,
    run_agent_loop_continue,
)
from codeagent.core.contracts.messages import (
    CleanupStatus,
    Message,
    OutputCompleteness,
    ToolCall,
    ToolExecutionStatus,
    ToolOutputMetadata,
    ToolResult,
)
from codeagent.core.contracts.ports import (
    AgentTool,
    ModelPort,
    ModelResponse,
    StreamEvent,
    ToolCleanupPort,
    ToolDecision,
)
from codeagent.core.orchestration.config import AgentLoopConfig

__all__ = [
    "AgentEvent",
    "HookPhase",
    "HookScope",
    "HookDiagnostic",
    "HookFailureStage",
    "LifecycleHook",
    "LifecycleHookEvent",
    "AgentContext",
    "Agent",
    "AgentContinueError",
    "AgentLoopConfig",
    "AgentRuntimeError",
    "ContextBudgetInput",
    "ContextBudgetPort",
    "ContextBudgetSnapshot",
    "ContextToolDefinition",
    "ContextPreparationRequest",
    "ContextPreparer",
    "ContextTransformer",
    "TransformContext",
    "ContextPreparationError",
    "ContextPreflightConfig",
    "ContextPreflightError",
    "ContextPreflightResult",
    "ContextTransformTimeoutError",
    "CleanupStatus",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_OUTPUT_RESERVE",
    "DEFAULT_RESERVE_TOKENS",
    "CleanupResult",
    "AgentTool",
    "DEFAULT_RECURSION_LIMIT",
    "EventType",
    "Message",
    "OutputCompleteness",
    "ModelPort",
    "ModelResponse",
    "OperationRegistry",
    "RecursionLimitError",
    "run_agent_loop",
    "run_agent_loop_continue",
    "StreamEvent",
    "ToolCall",
    "ToolDecision",
    "ToolCleanupPort",
    "ToolExecutionRuntime",
    "ToolExecutionStatus",
    "ToolOutputMetadata",
    "ToolOperation",
    "ToolResult",
    "PreflightStatus",
    "evaluate_context_preflight",
    "estimate_context_budget",
    "ContextDiagnostics",
    "govern_tool_messages",
    "classify_core_event",
    "classify_session_event",
    "core_event_scope_phase",
    "hook_name",
    "make_hook_diagnostic",
    "session_event_phase",
    "to_lifecycle_hook_event",
]
