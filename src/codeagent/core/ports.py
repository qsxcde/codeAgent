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

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from codeagent.core.messages import Message, ToolCall

__all__ = ["AgentPorts", "ModelPort", "ModelResponse", "StreamEvent"]


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


@dataclass(frozen=True)
class AgentPorts:
    """编排层的外部端口集合(自研版)。

    - ``model``:模型端口(组合根适配 ai 层 ChatClient);
    - ``tools``:工具列表(自研 AtomicTool 实例,直接 ``invoke``)。

    ``store`` 不在端口内:core 循环从不落盘(成功轮次才写由会话层负责),
    会话存储只经 ``AgentSession`` 注入(session-manager change 清理死字段)。
    """

    model: ModelPort
    tools: list[Any]
