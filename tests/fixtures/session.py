"""会话测试资源。"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.app.container import ChatModelPort
from codeagent.app.composition.tools.adapter import adapt_tools
from codeagent.core import AgentLoopConfig
from codeagent.session import AgentSession, EventBus
from codeagent.session.persistence import MemoryStore
from codeagent.tools.atomic import BashTool, EditTool, FindTool, GrepTool, LsTool, ReadTool, WriteTool


@pytest.fixture
def session_factory() -> Callable[..., AgentSession]:
    """构造带默认离线工具集的会话,允许测试覆盖 model/store/id。"""

    def factory(
        model: FakeClient | None = None,
        *,
        store=None,
        session_id: str | None = None,
    ) -> AgentSession:
        config = AgentLoopConfig(
            model=ChatModelPort(model or FakeClient(response="测试回复")),
            tools=adapt_tools(
                [ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool(), FindTool(), LsTool()]
            ),
        )
        return AgentSession(config, EventBus(), store=store, session_id=session_id)

    return factory


@pytest.fixture
def memory_store() -> MemoryStore:
    """隔离的内存 store,用于不需要 JSONL 落盘的会话测试。"""
    return MemoryStore()
