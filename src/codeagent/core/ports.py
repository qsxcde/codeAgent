"""core/ports.py:编排层端口——core 认识外部世界的唯一窗口。

自研编排(2026-08-14)后端口收敛为三样东西:
- ``model``:模型端口(实现方在组合根,内部对接 ai 层 ChatClient);
- ``tools``:工具列表(实现 ``name`` / ``description`` / ``args_schema`` /
  ``invoke(args_dict) -> str`` 即可);
- ``store``:会话存储(可选;None 表示不持久化,如一次性 headless)。

core 不 import config / ai / tools / session;端口类型定义在本模块,
组合根(唯一允许跨层的地方)负责把外部实现装配进来。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from codeagent.core.messages import Message, ToolCall, ToolResult

__all__ = [
    "AgentLoopConfig",
    "AgentTool",
    "ModelPort",
    "ModelResponse",
    "PolicyDecision",
    "StreamEvent",
    "Summarizer",
    "ToolDecision",
    "ToolExecutionRuntimePort",
]


@dataclass
class ModelResponse:
    """模型一次完整生成的结果(非流式路径)。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] | None = None  # {input_tokens, output_tokens, reasoning_tokens}
    finish_reason: str | None = None
    model: str = ""


@dataclass
class StreamEvent:
    """模型流式产出的统一事件(与 ai 层 SSE 解析同形,core 自有类型)。"""

    type: str  # content | thinking | tool_call_arg | finish | usage
    text: str = ""
    tool_index: int | None = None
    arg_delta: str = ""
    tool_name: str = ""
    tool_id: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    #: Parsed tool arguments supplied by the application model adapter.
    arguments: dict[str, Any] | None = None
    argument_error: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    """执行前安全策略的决策结果(design security-permissions)。

    - ``action``:allow(直接执行)/ ask(需用户确认)/ deny(拒绝执行);
    - ``reason``:决策原因(拒绝/确认时对模型与用户可见,审计用途);
    - ``warning``:放行但附带提示(如越界读),不影响执行。
    """

    action: str  # "allow" | "ask" | "deny"
    reason: str = ""
    warning: bool = False


class ApprovalPolicy(Protocol):
    """执行前安全策略端口:决定工具调用放行/需确认/拒绝。

    core 只认识决策形态;实现方在组合根(tools 层分类器适配),循环在
    每个工具调用执行前调用;``ask`` 由循环 emit 确认请求并等待会话队列。
    """

    def decide(self, tool_name: str, args: dict) -> PolicyDecision: ...


class ToolExecutionRuntimePort(Protocol):
    """Optional runtime port used by the ReAct loop for controlled execution."""

    async def execute(
        self,
        tool: Any,
        call: ToolCall,
        timeout: float | None = None,
        operation_id: str | None = None,
        on_update: Callable[[Any], Awaitable[None] | None] | None = None,
    ) -> Any: ...


class Summarizer(Protocol):
    """上下文压缩摘要端口(session-compaction):把被压缩窗口摘要化。

    - ``messages``:被压缩窗口的消息(完整轮次);
    - ``prev_summary``:上一次压缩的摘要(二次压缩增量合并,None = 首次);
    - 返回摘要文本;实现方在组合根(离线测试注入桩,真实实现接 LLM)。
    """

    async def summarize(
        self, messages: list[Message], prev_summary: str | None
    ) -> str: ...


class ModelPort(Protocol):
    """模型端口:编排循环消费的最小调用面(实现方在组合根)。"""

    @property
    def model_id(self) -> str: ...

    async def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> ModelResponse: ...

    def stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]: ...


@runtime_checkable
class AgentTool(Protocol):
    """Minimal tool contract consumed by the new Agent Runtime."""

    name: str
    description: str
    parameters: Any

    async def execute(
        self,
        tool_call_id: str,
        arguments: dict[str, Any],
        *,
        signal: Any = None,
        on_update: Callable[[Any], Awaitable[None] | None] | None = None,
    ) -> ToolResult | Any: ...


@dataclass(frozen=True)
class ToolDecision:
    """Generic pre-execution decision returned by an Agent hook."""

    action: str
    reason: str = ""

    @classmethod
    def allow(cls) -> "ToolDecision":
        return cls("allow")

    @classmethod
    def block(cls, reason: str) -> "ToolDecision":
        return cls("block", reason)


async def _identity_context(messages: list[Message]) -> list[Message]:
    return list(messages)


TransformContext = Callable[
    [list[Message]], Awaitable[list[Message]] | list[Message]
]
BeforeToolCall = Callable[
    [ToolCall, Any], Awaitable[ToolDecision | None] | ToolDecision | None
]
AfterToolCall = Callable[
    [ToolCall, ToolResult, Any],
    Awaitable[ToolResult | None] | ToolResult | None,
]


@dataclass
class AgentLoopConfig:
    """Configuration for the pure in-memory Agent loop."""

    model: Any
    tools: list[AgentTool] = field(default_factory=list)
    transform_context: TransformContext = _identity_context
    before_tool_call: BeforeToolCall | None = None
    after_tool_call: AfterToolCall | None = None
    tool_execution: str = "parallel"
    tool_timeout: float | None = None
    should_stop_after_turn: Callable[..., Awaitable[bool] | bool] | None = None
    tool_runtime: ToolExecutionRuntimePort | None = None
    #: Runtime-owned steering queue; Agent drains it between tool batches.
    steer_queue: list[str] = field(default_factory=list)
