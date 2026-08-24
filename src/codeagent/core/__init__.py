"""编排层:端口、事件、消息、循环(自研版,2026-08-14)。

分层约束:core 不 import config / ai / tools / session,仅依赖标准库与
本包内部模块。外部世界统一收敛到 `AgentPorts`(模型端口 / 工具 / 存储)。
"""

from codeagent.core.events import AgentEvent, EventType
from codeagent.core.execution import ToolExecutionRuntime, ToolOperation
from codeagent.core.loop import DEFAULT_RECURSION_LIMIT, RecursionLimitError, run_turn
from codeagent.core.messages import Message, ToolCall, ToolExecutionStatus, ToolResult
from codeagent.core.ports import AgentPorts, ModelPort, ModelResponse, StreamEvent

__all__ = [
    "AgentEvent",
    "AgentPorts",
    "DEFAULT_RECURSION_LIMIT",
    "EventType",
    "Message",
    "ModelPort",
    "ModelResponse",
    "RecursionLimitError",
    "StreamEvent",
    "ToolCall",
    "ToolExecutionRuntime",
    "ToolExecutionStatus",
    "ToolOperation",
    "ToolResult",
    "run_turn",
]
