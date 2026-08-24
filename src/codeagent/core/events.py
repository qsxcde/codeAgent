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
    MODEL_REQUEST_STARTED = "model_request_started"  # 一次模型请求开始
    MODEL_REQUEST_FINISHED = "model_request_finished"  # 一次模型请求结束
    TEXT_DELTA = "text_delta"                # 模型输出 token 增量
    THINKING_DELTA = "thinking_delta"        # 模型思考过程增量(推理模型 reasoning_content)
    AGENT_MESSAGE = "agent_message"          # 模型完整消息(回合结束)
    TOOL_CALL = "tool_call"                  # 模型请求调用工具
    TOOL_QUEUED = "tool_queued"              # 工具进入执行队列
    TOOL_STARTED = "tool_started"            # 工具开始执行
    TOOL_PROGRESS = "tool_progress"          # 工具可选进度
    TOOL_FINISHED = "tool_finished"          # 工具执行结束
    TOOL_RESULT = "tool_result"              # 工具执行结果
    TURN_END = "turn_end"                    # 一轮对话结束
    ERROR = "error"                          # 图运行出错(供订阅方感知并终止)
    RUN_CANCELLED = "run_cancelled"          # 运行被用户中断(abort 后由 session 广播)
    USAGE = "usage"                          # token 用量(模型 usage_metadata 透传)
    CONFIRMATION_REQUESTED = "confirmation_requested"  # 工具执行需用户确认(security-permissions)
    COMPACTION_STARTED = "compaction_started"          # 上下文压缩开始
    COMPACTION_FINISHED = "compaction_finished"        # 上下文压缩结束
    RESTORE_STARTED = "restore_started"                # 会话恢复开始
    RESTORE_FINISHED = "restore_finished"              # 会话恢复结束
    CANCELLING = "cancelling"                          # 用户请求取消
    RETRY_STARTED = "retry_started"                    # 失败后安全重试


@dataclass
class AgentEvent:
    """一次图运行中产生的事件。

    - ``type``:事件类型(EventType 常量);
    - ``payload``:随类型变化的负载(文本增量 / 消息 / 工具调用等)。
    """

    type: str
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    #: 下面的字段是 metadata 的类型化快捷入口，保留 metadata 以兼容旧订阅方。
    session_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
    operation_id: str | None = None
    phase: str | None = None
    elapsed_ms: int | None = None
    error_code: str | None = None
    retryable: bool | None = None
    cleanup_uncertain: bool | None = None
    side_effect_state: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - 仅调试展示
        return f"AgentEvent({self.type}, {self.payload!r})"
