"""组合根测试:假 provider 注入,create_agent_graph 零网络。

只验证组装与分层约束,不触发任何真实 LLM/网络请求。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from codeagent.ai.transport.openai_compat import OpenAICompatClient


def test_create_agent_graph_returns_compiled_graph():
    """用 fake provider 注入,零网络构建编译后的图。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_graph

        graph = create_agent_graph()
    # 编译后的图具备 invoke / astream 能力
    assert hasattr(graph, "invoke")
    assert hasattr(graph, "astream")
    # 默认注入了内存 checkpointer(可 aget_state)
    assert hasattr(graph, "aget_state")


def test_create_agent_session_returns_session():
    """create_agent_session 返回可订阅的 AgentSession。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_session

        sess = create_agent_session()
    assert hasattr(sess, "run")
    assert hasattr(sess, "subscribe")


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

    def set_footer(self, line) -> None:  # pragma: no cover - stub
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
    assert app.model.footer.model == ""
    assert app.model.footer.effort == ""


def test_create_tui_app_resolves_footer_info():
    """footer 的 model · effort 优先级:model 内联后缀 > provider 配置默认(design D5)。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="deepseek", model="deepseek-v4-pro:low", backend=_StubBackend())
        assert app.model.footer.model == "deepseek-v4-pro"
        assert app.model.footer.effort == "low"

        app = create_tui_app(provider="deepseek", backend=_StubBackend())
        assert app.model.footer.model == "deepseek-v4-flash"
        assert app.model.footer.effort == "high"


@pytest.mark.anyio
async def test_real_provider_runs_through_graph():
    """真实 OpenAICompatClient 经 create_agent_graph 接入 LangGraph 可跑通(回归:#1 + 流式路径)。

    早期缺陷:`bind_tools` 返回裸客户端(无 ainvoke),agent 节点调用 `bound_model.ainvoke`
    抛 AttributeError。现 agent 节点改走 `astream` 消费流式增量,这里用 httpx.MockTransport
    同时覆盖 `stream` 路径(不再只 patch `post`),断言图能正常产出 AIMessage。
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

    from codeagent.app.container import create_agent_graph
    from langchain_core.messages import AIMessage

    final = None
    with patch("codeagent.ai.factory.create_llm", return_value=llm), patch(
        "codeagent.ai.transport.openai_compat.httpx.AsyncClient",
        return_value=mock_async_client,
    ):
        graph = create_agent_graph()
        async for item in graph.astream(
            {"messages": []},
            config={"configurable": {"thread_id": "t1"}},
            stream_mode=["updates"],
        ):
            # 多 stream_mode(list 形式)时 item 为 (mode, payload) 元组
            update = item[1] if isinstance(item, tuple) else item
            for node, state_update in update.items():
                for msg in state_update.get("messages", []):
                    if isinstance(msg, AIMessage):
                        final = msg

    assert final is not None
    assert final.content == "ok"
