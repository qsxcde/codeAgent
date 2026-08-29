"""Shared helpers for split behavior tests."""

from __future__ import annotations
import asyncio
import pytest
from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.app.composition.tools.adapter import adapt_tools
from codeagent.core import AgentLoopConfig, EventType, Message, RecursionLimitError
from codeagent.session import AgentSession, EventBus
from codeagent.session.store import MemoryStore
from codeagent.tools.atomic import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    WriteTool,
)

def _session(model: FakeClient, store=None, session_id: str | None = None) -> AgentSession:
    config = AgentLoopConfig(
        model=ChatModelPort(model),
        tools=adapt_tools(
            [ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()]
        ),
    )
    return AgentSession(config, EventBus(), store=store, session_id=session_id)


def _event_types(seen) -> list[str]:
    return [e.type for e in seen]


class _StubPolicy:
    """脚本化策略:按工具名返回预设动作(会话层测试用,与 core 测试同形)。"""

    def __init__(self, action_by_tool: dict[str, str]) -> None:
        self._action_by_tool = action_by_tool

    def decide(self, tool_name: str, args: dict):
        from codeagent.core.contracts.ports import PolicyDecision

        return PolicyDecision(
            self._action_by_tool.get(tool_name, "allow"), reason=f"stub:{tool_name}"
        )


def _session_with_policy(
    model: FakeClient,
    policy=None,
    store=None,
    session_id: str | None = None,
    confirmation_timeout: float | None = None,
) -> AgentSession:
    config = AgentLoopConfig(
        model=ChatModelPort(model),
        tools=adapt_tools(
            [ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()]
        ),
    )
    return AgentSession(
        config,
        EventBus(),
        store=store,
        session_id=session_id,
        policy=policy,
        confirmation_timeout=confirmation_timeout,
    )


def _ask_model() -> FakeClient:
    """单轮 bash echo ok 后回复的 FakeClient(ask 路径用)。"""
    return FakeClient(
        steps=[
            {
                "content": "",
                "tool_calls": [
                    {"name": "bash", "args": {"command": "echo ok"}, "id": "c1", "type": "tool_call"}
                ],
            },
            {"content": "完成"},
        ]
    )


def _subscribe_confirmation(session, seen: list) -> asyncio.Event:
    """订阅事件并通过 Event 等待确认请求,避免轮询固定时间间隔。"""
    ready = asyncio.Event()

    def on_event(event) -> None:
        seen.append(event)
        if event.type == EventType.CONFIRMATION_REQUESTED:
            ready.set()

    session.subscribe(on_event)
    return ready


def _long(text: str) -> str:
    """长文本输入(每条消息 ≈ 25 token,配合预算 50 触发压缩)。"""
    return text + "x" * 100


class _StubSummarizer:
    """桩摘要:记录调用(窗口 / 既有摘要),返回可断言的拼接文本。"""

    def __init__(self) -> None:
        self.calls: list[tuple[list, str | None]] = []

    async def summarize(self, messages, prev_summary):
        self.calls.append((list(messages), prev_summary))
        window = "|".join(m.content[:6] for m in messages if m.content)
        return f"SUM[{window}]" + (f"<{prev_summary}>" if prev_summary else "")


class _FailingSummarizer:
    async def summarize(self, messages, prev_summary):
        raise RuntimeError("摘要服务失败")


def _compact_session(
    model: FakeClient,
    store=None,
    summarizer=None,
    context_window: int = 128_000,
    compact_budget: int = 50,
) -> AgentSession:
    """构造带 Summarizer 的会话(port 直装,不跨组合根;预算注入小值便于离线测)。"""
    config = AgentLoopConfig(
        model=ChatModelPort(model),
        tools=adapt_tools(
            [ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()]
        ),
    )
    return AgentSession(
        config,
        EventBus(),
        store=store,
        summarizer=summarizer,
        context_window=context_window,
        compact_budget=compact_budget,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
