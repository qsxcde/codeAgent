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


def test_create_tui_app_injects_rebuild_ports():
    """组合根注入 rebuild 回调:/provider /model /effort 热切换链路(T-44)。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.session.store import MemoryStore

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        store = MemoryStore()
        app = create_tui_app(provider="fake", backend=_StubBackend(), store=store)
    assert app._rebuild_ports is not None
    model_id, effort = app._rebuild_ports("fake", "fake-model:high", None)
    assert model_id == "fake-model"
    assert effort == "high"
    # 配置写入 store(model_change 后写覆盖)且会话端口已更新
    ref = store.list()[-1]
    assert ref.model == "fake-model" and ref.effort == "high"
    assert app._manager._ports is not None


def test_create_tui_app_injects_selector_candidates():
    """选择器候选经组合根注入(T-45):provider/model/effort 各一份。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend())
    candidates = app._candidates
    assert "deepseek" in candidates["provider"]
    assert "fake" in candidates["provider"]
    assert candidates["effort"] == ["low", "medium", "high"]
    assert isinstance(candidates["model"], list)


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


# -- 执行前安全策略装配(security-permissions)----------------------------------


def _ports_with_mode(approval_mode: str):
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_ports

        return create_agent_ports(approval_mode=approval_mode)


def test_policy_deny_mode_default_and_fails_closed():
    """缺省/deny 模式:ask 降级 deny(未确认不得执行);allow 直通。"""
    ports = _ports_with_mode("deny")
    assert ports.policy is not None
    assert ports.policy.decide("bash", {"command": "git push"}).action == "deny"
    assert "未确认不得执行" in ports.policy.decide("bash", {"command": "git push"}).reason
    assert ports.policy.decide("bash", {"command": "ls"}).action == "allow"
    assert ports.policy.decide("bash", {"command": "rm -rf /"}).action == "deny"  # 黑名单


def test_policy_interactive_mode_keeps_ask():
    """interactive 模式(TUI):ask 保留,交用户确认。"""
    ports = _ports_with_mode("interactive")
    decision = ports.policy.decide("bash", {"command": "git push"})
    assert decision.action == "ask" and "推送" in decision.reason


def test_policy_allow_mode_approves_asks():
    """allow 模式(--yes):ask 放行(显式承担风险)。"""
    ports = _ports_with_mode("allow")
    assert ports.policy.decide("bash", {"command": "git push"}).action == "allow"
    assert ports.policy.decide("bash", {"command": "rm -rf /"}).action == "deny"  # 黑名单仍拦


def test_policy_file_boundary_modes(tmp_path, monkeypatch):
    """文件边界经装配生效:越界写 interactive → ask;deny → 拒绝;界内写 → allow。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ws").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    monkeypatch.setenv("CODEAGENT_CWD", str(tmp_path))

    interactive = _ports_with_mode("interactive")
    decision = interactive.policy.decide("write", {"file_path": "ws/a.py"})
    assert decision.action == "allow"  # 界内
    decision = interactive.policy.decide("write", {"file_path": "../secret.txt"})
    assert decision.action == "ask"  # 越界写 → 确认
    deny = _ports_with_mode("deny")
    assert deny.policy.decide("write", {"file_path": "../secret.txt"}).action == "deny"
    read = interactive.policy.decide("read", {"file_path": "../secret.txt"})
    assert read.action == "allow" and read.warning is True  # 越界读警告放行


# -- 系统提示词注入(agents-md-hierarchy)---------------------------------------


def test_ports_inject_system_prompt_with_agents(tmp_path, monkeypatch):
    """组合根装配:system prompt = 基础提示词 + 分层 AGENTS.md(首条 system 消息)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("项目级指令", encoding="utf-8")
    from codeagent.app.config import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "AGENTS.md").write_text("全局指令", encoding="utf-8")
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        model = FakeClient(response="测试回复")
        mock_llm.return_value = model
        from codeagent.app.container import create_agent_ports, agents_sources

        ports = create_agent_ports()
        sources = agents_sources()
    assert sources  # 全局 + 项目文件被加载
    assert any(str(CONFIG_DIR / "AGENTS.md") in s for s in sources)
    assert any(str(tmp_path / "AGENTS.md") in s for s in sources)
    # 运行一轮:模型收到的首条消息为 system,含基础提示词 + 来源标注
    import asyncio

    from codeagent.core import run_turn

    events: list = []
    asyncio.run(run_turn(ports, events.append, "你好", history=[]))
    assert model.call_history
    first = model.call_history[0]["messages"][0]
    assert first["role"] == "system"
    assert "codeagent" in first["content"]  # 基础提示词
    assert "项目级指令" in first["content"]
    assert '<project_instructions path="' in first["content"]
    assert "全局指令" in first["content"]


def test_system_prompt_only_once_and_hot_swap_stable(tmp_path, monkeypatch):
    """system 只首插一次(重复调用不叠加);热切换后仍携带。"""
    monkeypatch.chdir(tmp_path)
    from codeagent.app.config import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "AGENTS.md").write_text("全局指令", encoding="utf-8")
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        model = FakeClient(responses=["第一轮", "第二轮"])
        mock_llm.return_value = model
        from codeagent.app.container import create_agent_ports

        ports = create_agent_ports()
    import asyncio

    from codeagent.core import run_turn

    events: list = []
    asyncio.run(run_turn(ports, events.append, "第一问", history=[]))
    asyncio.run(run_turn(ports, events.append, "第二问", history=[]))
    for call in model.call_history:
        roles = [m["role"] for m in call["messages"]]
        assert roles.count("system") == 1  # 每轮恰好一条
        assert roles[0] == "system"


# -- 上下文压缩装配(session-compaction)----------------------------------------


class _StubSummarizer:
    async def summarize(self, messages, prev_summary):
        return "桩摘要" + (f"<{prev_summary}>" if prev_summary else "")


def test_session_with_summarizer_can_compact():
    """注入桩 Summarizer 的会话可压缩;压缩不可用(未注入)时明确报错。"""
    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_session

        session = create_agent_session(summarizer=_StubSummarizer())
        assert asyncio.run(session.compact()) is False  # 空历史:全保留,不压缩
        from codeagent.session import AgentSession

        plain = create_agent_session()
        with pytest.raises(ValueError, match="压缩不可用"):
            asyncio.run(plain.compact())


def test_tui_app_gets_compaction_capable_manager():
    """create_tui_app 装配 Summarizer:/compact 可经 current 会话执行。"""
    from codeagent.app.container import create_tui_app
    from codeagent.app.tui.backend import TuiBackend

    class StubBackend(TuiBackend):
        def run(self):
            pass

        def transcript_size(self):
            return 80, 24

        def render(self, lines):
            pass

        def set_status(self, line):
            pass

        def set_suggestions(self, lines):
            pass

        def set_input_text(self, text):
            pass

        def on_submit(self, handler):
            pass

        def on_interrupt(self, handler):
            pass

        def on_resize(self, handler):
            pass

        def on_click(self, handler):
            pass

        def on_input_changed(self, handler):
            pass

        def on_suggestion_navigate(self, handler):
            pass

        def on_suggestion_confirm(self, handler):
            pass

        def on_scroll(self, handler):
            pass

        def set_confirmation(self, lines):
            pass

        def on_confirmation_response(self, handler):
            pass

        def exit_document(self, lines):
            pass

        def stop(self):
            pass

    with patch("codeagent.ai.factory.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        app = create_tui_app(backend=StubBackend())
    assert app._manager.current is not None
    assert app._manager._summarizer is not None  # /compact 可用
