"""编排层事件类型:把图运行翻译成可供订阅方感知的事件。

`core/` 只定义事件的数据形态,不负责路由;事件经 `session/bus.py`
的 EventBus 分发到订阅方(TUI / CLI / 测试)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class EventType:
    """事件类型常量(字符串,便于序列化与比较)。"""

    SESSION_STARTED = "session_started"      # 一轮对话开始
    TEXT_DELTA = "text_delta"                # 模型输出 token 增量
    THINKING_DELTA = "thinking_delta"        # 模型思考过程增量(推理模型 reasoning_content)
    AGENT_MESSAGE = "agent_message"          # 模型完整消息(回合结束)
    TOOL_CALL = "tool_call"                  # 模型请求调用工具
    TOOL_RESULT = "tool_result"              # 工具执行结果
    TURN_END = "turn_end"                    # 一轮对话结束
    ERROR = "error"                          # 图运行出错(供订阅方感知并终止)
    RUN_CANCELLED = "run_cancelled"          # 运行被用户中断(abort 后由 session 广播)
    USAGE = "usage"                          # token 用量(模型 usage_metadata 透传)


@dataclass
class AgentEvent:
    """一次图运行中产生的事件。

    - ``type``:事件类型(EventType 常量);
    - ``payload``:随类型变化的负载(文本增量 / 消息 / 工具调用等)。
    """

    type: str
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试展示
        return f"AgentEvent({self.type}, {self.payload!r})"
