"""组合根测试:假 provider 注入,自研端口/会话装配零网络。

只验证组装与分层约束,不触发任何真实 LLM/网络请求。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from codeagent.ai.transport.openai_compat import OpenAICompatClient


def test_create_agent_ports_returns_ports():
    """用 fake provider 注入,零网络装配自研端口(模型端口 + 工具)。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_ports
        from codeagent.core.ports import AgentPorts

        ports = create_agent_ports()
    assert isinstance(ports, AgentPorts)
    assert len(ports.tools) == 7
    assert ports.model.model_id == "fake-model"


def test_create_agent_session_returns_session():
    """create_agent_session 返回可订阅的 AgentSession。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_session

        sess = create_agent_session()
    assert hasattr(sess, "run")
    assert hasattr(sess, "subscribe")
    assert hasattr(sess, "abort")
    assert hasattr(sess, "steer")


class _StubBackend:
    """最小 TuiBackend 实现(不 import textual,离线装配断言)。"""

    def run(self) -> None:  # pragma: no cover - stub
        pass

    def transcript_size(self) -> tuple[int, int]:
        return 60, 10

    def render(self, lines) -> None:  # pragma: no cover - stub
        pass

    def set_status(self, line) -> None:  # pragma: no cover - stub
        pass

    def on_submit(self, handler) -> None:  # pragma: no cover - stub
        pass

    def on_interrupt(self, handler) -> None:  # pragma: no cover - stub
        pass

    def on_resize(self, handler) -> None:  # pragma: no cover - stub
        pass

    def on_click(self, handler) -> None:  # pragma: no cover - stub
        pass

    def exit_document(self, lines) -> None:  # pragma: no cover - stub
        pass

    def stop(self) -> None:  # pragma: no cover - stub
        pass


def test_create_tui_app_assembles_with_stub_backend():
    """create_tui_app 装配 session + backend,不依赖 textual(design D5)。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend())
    assert hasattr(app, "start")
    # fake provider 无 Config 类:状态栏 model/effort 为空,但 cwd 仍注入
    assert app.model.status.model == ""
    assert app.model.status.effort == ""
    assert app.model.status.cwd != ""


def test_create_tui_app_resolves_footer_info():
    """状态栏装配数据的 model · effort 优先级:model 内联后缀 > provider 配置默认(design D5)。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="deepseek", model="deepseek-v4-pro:low", backend=_StubBackend())
        assert app.model.status.model == "deepseek-v4-pro"
        assert app.model.status.effort == "low"

        app = create_tui_app(provider="deepseek", backend=_StubBackend())
        assert app.model.status.model == "deepseek-v4-flash"
        assert app.model.status.effort == "high"


@pytest.mark.anyio
async def test_real_provider_runs_through_loop():
    """真实 OpenAICompatClient 经自研循环可跑通(回归:#1 + 流式路径)。

    早期缺陷:`bind_tools` 返回裸客户端(无 ainvoke),langgraph agent 节点调用
    ``bound_model.ainvoke`` 抛 AttributeError。自研循环直接消费流式事件,
    这里用 httpx.MockTransport 覆盖 stream 路径,断言事件序列与消息产出。
    """
    llm = OpenAICompatClient(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
    )

    sse_body = (
        'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}\n\n'
        "data: [DONE]\n\n"
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=sse_body.encode(), headers={"content-type": "text/event-stream"}
        )
    )
    mock_async_client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10.0))

    from codeagent.app.container import create_agent_ports
    from codeagent.core import EventType, run_turn

    events = []
    with patch("codeagent.ai.factory.create_llm", return_value=llm), patch(
        "codeagent.ai.transport.openai_compat.httpx.AsyncClient",
        return_value=mock_async_client,
    ):
        ports = create_agent_ports()
        history = await run_turn(ports, events.append, "hi", history=[])
        await ports.model._client.aclose()

    types = [e.type for e in events]
    assert EventType.TEXT_DELTA in types
    assert history[-1].role == "assistant"
    assert history[-1].content == "ok"
