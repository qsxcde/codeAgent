"""编排层:端口、事件、消息、循环(自研版,2026-08-14)。

分层约束:core 不 import config / ai / tools / session,仅依赖标准库与
本包内部模块。外部世界通过 AgentLoopConfig 注入模型、工具和运行时。
"""

from codeagent.core.context import AgentContext
from codeagent.core.context_budget import (
    ContextBudgetInput,
    ContextBudgetSnapshot,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_OUTPUT_RESERVE,
    DEFAULT_RESERVE_TOKENS,
    estimate_context_budget,
)
from codeagent.core.context_preflight import (
    ContextPreflightConfig,
    ContextPreflightResult,
    PreflightStatus,
    evaluate_context_preflight,
)
from codeagent.core.agent import Agent
from codeagent.core.errors import (
    AgentContinueError,
    AgentRuntimeError,
    ContextPreparationError,
    ContextPreflightError,
)
from codeagent.core.events import AgentEvent, EventType
from codeagent.core.execution import (
    CleanupResult,
    OperationRegistry,
    ToolExecutionRuntime,
    ToolOperation,
)
from codeagent.core.loop import (
    DEFAULT_RECURSION_LIMIT,
    RecursionLimitError,
    run_agent_loop,
    run_agent_loop_continue,
)
from codeagent.core.messages import (
    CleanupStatus,
    Message,
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
)
from codeagent.core.ports import (
    AgentLoopConfig,
    AgentTool,
    ContextBudgetPort,
    ContextPreparationRequest,
    ContextPreparer,
    ContextToolDefinition,
    ModelPort,
    ModelResponse,
    StreamEvent,
    ToolDecision,
)

__all__ = [
    "AgentEvent",
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
    "ContextPreparationError",
    "ContextPreflightConfig",
    "ContextPreflightError",
    "ContextPreflightResult",
    "CleanupStatus",
    "DEFAULT_CONTEXT_WINDOW",
    "DEFAULT_OUTPUT_RESERVE",
    "DEFAULT_RESERVE_TOKENS",
    "CleanupResult",
    "AgentTool",
    "DEFAULT_RECURSION_LIMIT",
    "EventType",
    "Message",
    "ModelPort",
    "ModelResponse",
    "OperationRegistry",
    "RecursionLimitError",
    "run_agent_loop",
    "run_agent_loop_continue",
    "StreamEvent",
    "ToolCall",
    "ToolDecision",
    "ToolExecutionRuntime",
    "ToolExecutionStatus",
    "ToolOperation",
    "ToolResult",
    "PreflightStatus",
    "evaluate_context_preflight",
    "estimate_context_budget",
]
