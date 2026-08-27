"""AI 测试资源:离线 fake client 和简单构造器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from codeagent.ai.providers.fake import FakeClient
from codeagent.core.events import AgentEvent


@pytest.fixture
def fake_client_factory() -> Callable[..., FakeClient]:
    """返回 FakeClient 构造器,确保测试不依赖真实凭据或网络。"""
    return FakeClient


@pytest.fixture
def fake_client() -> FakeClient:
    """默认离线模型,用于只关心运行时流程的测试。"""
    return FakeClient(response="测试回复")


@pytest.fixture
def agent_event_factory() -> Callable[..., AgentEvent]:
    """构造带可选运行元数据的模型/工具事件。"""

    def build(event_type: str, payload: Any = None, **metadata: Any) -> AgentEvent:
        return AgentEvent(event_type, payload=payload, metadata=metadata)

    return build
