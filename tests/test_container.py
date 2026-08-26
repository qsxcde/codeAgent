"""组合根测试:假 provider 注入,自研端口/会话装配零网络。

只验证组装与分层约束,不触发任何真实 LLM/网络请求。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from codeagent.ai.transport.openai_compat import OpenAICompatClient


async def _run_config(config, prompt: str, *, history=None, emit=None):
    from codeagent.core import AgentContext, run_agent_loop

    previous = list(history or [])
    new_messages = await run_agent_loop(
        AgentContext(messages=previous, tools=list(config.tools)),
        config,
        prompt,
        emit=emit,
    )
    return previous + new_messages


def test_create_agent_config_returns_config():
    """用 fake provider 注入,零网络装配自研端口(模型端口 + 工具)。"""
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config
        from codeagent.core.ports import AgentLoopConfig

        config = create_agent_config()
    assert isinstance(config, AgentLoopConfig)
    assert len(config.tools) == 8
    assert config.model.model_id == "fake-model"


def test_create_agent_config_injects_shared_tool_runtime():
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config
        from codeagent.core.execution import ToolExecutionRuntime

    config = create_agent_config()

    assert isinstance(config.tool_runtime, ToolExecutionRuntime)


def test_agent_runtime_close_is_idempotent():
    """Composition-root runtime closes model resources exactly once."""
    from codeagent.app.container import AgentRuntime
    from codeagent.core.ports import AgentLoopConfig

    class Closable:
        model_id = "stub"

        def __init__(self):
            self.closed = 0

        async def aclose(self):
            self.closed += 1

    client = Closable()
    config = AgentLoopConfig(model=client, tools=[])
    runtime = AgentRuntime(config, None, client, [])
    asyncio.run(runtime.close())
    asyncio.run(runtime.close())
    assert client.closed == 1


def test_agent_runtime_is_removed_from_registry_after_close():
    from codeagent.app.container import AgentRuntime, runtime_for_config
    from codeagent.core.ports import AgentLoopConfig

    class Closable:
        async def aclose(self):
            pass

    client = Closable()
    config = AgentLoopConfig(model=client, tools=[])
    runtime = AgentRuntime(config, None, client, [])
    from codeagent.app.composition.runtime_factory import _RUNTIMES_BY_CONFIG

    _RUNTIMES_BY_CONFIG[id(config)] = runtime
    asyncio.run(runtime.close())
    assert runtime_for_config(config) is None


def test_create_agent_session_returns_session():
    """create_agent_session 返回可订阅的 AgentSession。"""
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
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
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
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
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="deepseek", model="deepseek-v4-pro:low", backend=_StubBackend())
        assert app.model.status.model == "deepseek-v4-pro"
        assert app.model.status.effort == "low"

        app = create_tui_app(provider="deepseek", backend=_StubBackend())
        assert app.model.status.model == "deepseek-v4-flash"
        assert app.model.status.effort == "high"


def test_create_tui_app_injects_rebuild_config():
    """组合根注入 rebuild 回调:/provider /model /effort 热切换链路(T-44)。"""
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
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
    # 空会话尚未产生对话,配置只更新内存 pending session,不创建 store header。
    assert store.list() == []
    assert app._manager._config is not None


def test_rebuild_config_syncs_model_context_window():
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.app.container import create_tui_app

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("fake", {})["small-model"] = ModelSpec(
            id="small-model", context_window=32_000
        )
        app = create_tui_app(
            provider="fake", model="small-model", registry=registry, backend=_StubBackend()
        )
        assert app._manager.current.context_window == 32_000
        app._rebuild_ports("fake", "small-model", None)

    assert app._manager.current.context_window == 32_000


def test_rebuild_config_closes_realized_previous_runtime():
    """TUI 热切换在新端口构造成功后释放旧模型客户端。"""
    from codeagent.app.container import create_tui_app

    class ClosableClient:
        model_id = "fake-model"

        def __init__(self):
            self.closed = 0

        async def aclose(self):
            self.closed += 1

    clients: list[ClosableClient] = []

    def make_client(*args, **kwargs):
        client = ClosableClient()
        clients.append(client)
        return client

    with patch("codeagent.app.composition.model_selection.create_llm", side_effect=make_client):
        app = create_tui_app(provider="fake", backend=_StubBackend())
        # TUI 端口是 lazy 的，先访问共享工具以实现旧 runtime。
        _ = app._manager.tools
        assert len(clients) == 1
        app._rebuild_ports("fake", "fake-model:high", None)

    assert len(clients) == 2
    assert clients[0].closed == 1
    assert clients[1].closed == 0


def test_create_tui_app_injects_selector_candidates():
    """选择器候选经组合根注入(T-45):provider/model/effort 各一份。"""
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend())
    candidates = app._candidates
    assert "deepseek" in candidates["provider"]
    assert "fake" in candidates["provider"]
    assert candidates["effort"] == ["low", "medium", "high"]
    assert isinstance(candidates["model"], dict)
    assert "deepseek" in candidates["model"]
    assert candidates["model"]["deepseek"] == sorted(candidates["model"]["deepseek"])


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

    from codeagent.app.container import create_agent_config
    from codeagent.core import EventType

    events = []
    with patch("codeagent.app.composition.model_selection.create_llm", return_value=llm), patch(
        "codeagent.ai.transport.openai_compat.httpx.AsyncClient",
        return_value=mock_async_client,
    ):
        config = create_agent_config()
        history = await _run_config(config, "hi", emit=events.append)
        await config.model._client.aclose()

    types = [e.type for e in events]
    assert EventType.MESSAGE_UPDATE in types
    assert history[-1].role == "assistant"
    assert history[-1].content == "ok"


# -- 执行前安全策略装配(security-permissions)----------------------------------


def _config_with_mode(approval_mode: str):
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config

        config = create_agent_config(approval_mode=approval_mode)
        from codeagent.app.container import _create_policy

        return config, _create_policy(approval_mode=approval_mode)


def test_policy_deny_mode_default_and_fails_closed():
    """缺省/deny 模式:ask 降级 deny(未确认不得执行);allow 直通。"""
    _, policy = _config_with_mode("deny")
    assert policy.decide("bash", {"command": "git push"}).action == "deny"
    assert "未确认不得执行" in policy.decide("bash", {"command": "git push"}).reason
    assert policy.decide("bash", {"command": "ls"}).action == "allow"
    assert policy.decide("bash", {"command": "rm -rf /"}).action == "deny"  # 黑名单


def test_policy_interactive_mode_keeps_ask():
    """interactive 模式(TUI):ask 保留,交用户确认。"""
    _, policy = _config_with_mode("interactive")
    decision = policy.decide("bash", {"command": "git push"})
    assert decision.action == "ask" and "推送" in decision.reason


def test_policy_allow_mode_approves_asks():
    """allow 模式(--yes):ask 放行(显式承担风险)。"""
    _, policy = _config_with_mode("allow")
    assert policy.decide("bash", {"command": "git push"}).action == "allow"
    assert policy.decide("bash", {"command": "rm -rf /"}).action == "deny"  # 黑名单仍拦


def test_policy_file_boundary_modes(tmp_path, monkeypatch):
    """文件边界经装配生效:越界写 interactive → ask;deny → 拒绝;界内写 → allow。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ws").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    monkeypatch.setenv("CODEAGENT_CWD", str(tmp_path))

    _, interactive = _config_with_mode("interactive")
    decision = interactive.decide("write", {"file_path": "ws/a.py"})
    assert decision.action == "allow"  # 界内
    decision = interactive.decide("write", {"file_path": "../secret.txt"})
    assert decision.action == "ask"  # 越界写 → 确认
    _, deny = _config_with_mode("deny")
    assert deny.decide("write", {"file_path": "../secret.txt"}).action == "deny"
    read = interactive.decide("read", {"file_path": "../secret.txt"})
    assert read.action == "allow" and read.warning is True  # 越界读警告放行


# -- 系统提示词注入(agents-md-hierarchy)---------------------------------------


def test_config_inject_system_prompt_with_agents(tmp_path, monkeypatch):
    """组合根装配:system prompt = 基础提示词 + 分层 AGENTS.md(首条 system 消息)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("项目级指令", encoding="utf-8")
    from codeagent.app.config import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "AGENTS.md").write_text("全局指令", encoding="utf-8")
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        model = FakeClient(response="测试回复")
        mock_llm.return_value = model
        from codeagent.app.container import create_agent_config, agents_sources

        ports = create_agent_config()
        sources = agents_sources()
    assert sources  # 全局 + 项目文件被加载
    assert any(str(CONFIG_DIR / "AGENTS.md") in s for s in sources)
    assert any(str(tmp_path / "AGENTS.md") in s for s in sources)
    # 运行一轮:模型收到的首条消息为 system,含基础提示词 + 来源标注
    import asyncio

    events: list = []
    asyncio.run(_run_config(ports, "你好", emit=events.append))
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
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        model = FakeClient(responses=["第一轮", "第二轮"])
        mock_llm.return_value = model
        from codeagent.app.container import create_agent_config

        ports = create_agent_config()
    import asyncio

    events: list = []
    history = asyncio.run(_run_config(ports, "第一问", emit=events.append))
    asyncio.run(_run_config(ports, "第二问", history=history, emit=events.append))
    for call in model.call_history:
        roles = [m["role"] for m in call["messages"]]
        assert roles.count("system") == 1  # 每轮恰好一条
        assert roles[0] == "system"


def test_bootstrap_is_present_once_per_model_context_for_new_and_recovered_turns(tmp_path, monkeypatch):
    """Bootstrap 随每个新模型上下文出现一次，普通轮次不在历史中重复堆积。"""
    import json

    from codeagent.app.skill_packages import PackageManager
    from codeagent.app.skill_runtime import BOOTSTRAP_TAG

    source = tmp_path / "superpowers"
    (source / "skills" / "using-superpowers").mkdir(parents=True)
    (source / "skills" / "using-superpowers" / "SKILL.md").write_text(
        "---\ndescription: bootstrap\n---\n检查任务相关 Skill。", encoding="utf-8"
    )
    (source / "skills" / "fmt").mkdir()
    (source / "skills" / "fmt" / "SKILL.md").write_text(
        "---\ndescription: format\n---\n普通正文", encoding="utf-8"
    )
    (source / "codeagent-package.json").write_text(
        json.dumps({"id": "superpowers", "bootstrap": "using-superpowers"}),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    PackageManager(home, tmp_path).install(source)
    monkeypatch.setattr("codeagent.app.config.CONFIG_DIR", home)
    monkeypatch.chdir(tmp_path)

    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        model = FakeClient(responses=["第一轮", "第二轮"])
        mock_llm.return_value = model
        from codeagent.app.container import create_agent_config

        ports = create_agent_config()

    events: list = []
    history: list = []
    history = asyncio.run(_run_config(ports, "第一问", history=history, emit=events.append))
    history = asyncio.run(_run_config(ports, "第二问", history=history, emit=events.append))
    assert history
    for call in model.call_history:
        roles = [message["role"] for message in call["messages"]]
        assert roles.count("system") == 1
        assert BOOTSTRAP_TAG in call["messages"][0]["content"]


def test_bootstrap_is_reinjected_after_context_compaction(tmp_path, monkeypatch):
    """压缩重建上下文后，下一轮仍带 Bootstrap 和工具映射。"""
    import json

    from codeagent.app.skill_packages import PackageManager
    from codeagent.app.skill_runtime import BOOTSTRAP_TAG
    from codeagent.core import AgentLoopConfig
    from codeagent.session import EventBus
    from codeagent.session import AgentSession

    source = tmp_path / "superpowers"
    (source / "skills" / "using-superpowers").mkdir(parents=True)
    (source / "skills" / "using-superpowers" / "SKILL.md").write_text(
        "---\ndescription: bootstrap\n---\n检查任务相关 Skill。", encoding="utf-8"
    )
    (source / "codeagent-package.json").write_text(
        json.dumps({"id": "superpowers", "bootstrap": "using-superpowers"}),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    PackageManager(home, tmp_path).install(source)
    monkeypatch.setattr("codeagent.app.config.CONFIG_DIR", home)
    monkeypatch.chdir(tmp_path)

    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        model = FakeClient(responses=["答1", "答2", "答3", "答4"])
        mock_llm.return_value = model
        from codeagent.app.container import create_agent_config

        ports = create_agent_config()

    session = AgentSession(
        ports,
        EventBus(),
        summarizer=_StubSummarizer(),
        compact_budget=50,
    )
    for text in ("问1" * 40, "问2" * 40, "问3" * 40):
        asyncio.run(session.run(text))
    assert asyncio.run(session.compact()) is True
    asyncio.run(session.run("问4" * 40))
    assert BOOTSTRAP_TAG in model.call_history[-1]["messages"][0]["content"]


def test_config_inject_skills_section_and_tool(tmp_path, monkeypatch):
    """组合根装配:system prompt 追加技能段 + skill 工具携带渲染注册表。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".codeagent" / "skills" / "fmt").mkdir(parents=True)
    (tmp_path / ".codeagent" / "skills" / "fmt" / "SKILL.md").write_text(
        "---\ndescription: 格式化。\n---\n格式化正文", encoding="utf-8"
    )
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        model = FakeClient(response="测试回复")
        mock_llm.return_value = model
        from codeagent.app.container import create_agent_config

        ports = create_agent_config()
    import asyncio

    events: list = []
    asyncio.run(_run_config(ports, "你好", emit=events.append))
    first = model.call_history[0]["messages"][0]
    assert "<available_skills>" in first["content"]
    assert "- fmt: 格式化。 (来源:" in first["content"]
    assert "格式化正文" not in first["content"]  # 正文不预载
    skill_tool = next(t for t in ports.tools if getattr(t, "name", "") == "skill")
    out = skill_tool.invoke(skill_tool.Args(name="fmt"))
    assert "格式化正文" in out
    out = skill_tool.invoke(skill_tool.Args(name="nope"))
    assert "技能不存在" in out


# -- 上下文压缩装配(session-compaction)----------------------------------------


class _StubSummarizer:
    async def summarize(self, messages, prev_summary):
        return "桩摘要" + (f"<{prev_summary}>" if prev_summary else "")


def test_session_with_summarizer_can_compact():
    """注入桩 Summarizer 的会话可压缩;压缩不可用(未注入)时明确报错。"""
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
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

    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        app = create_tui_app(backend=StubBackend())
    assert app._manager.current is not None
    assert app._manager._summarizer is not None  # /compact 可用


# -- /login 密钥保存(tui-login-command) --------------------------------------


def test_create_tui_app_injects_save_key(tmp_path, monkeypatch):
    """组合根注入 save_key:/login 写 .env(<PREFIX>_API_KEY)并热切换。"""
    from codeagent.app import config as app_config

    env_file = tmp_path / ".codeagent" / ".env"
    monkeypatch.setattr(app_config, "CONFIG_ENV_FILE", env_file)
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="deepseek", backend=_StubBackend())
        # _save_key 会热切换重建端口(再走 create_llm),必须留在 mock 作用域内,
        # 否则无 key 机器上触达真实工厂抛 ValueError(审计 M-2)
        assert app._save_key is not None
        model_id, effort = app._save_key("deepseek", "sk-ds-1")
    content = env_file.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-ds-1" in content
    # 热切换生效:manager 端口重建,model/effort 按装配解析返回
    assert app._manager._config is not None
    assert (model_id, effort) == ("deepseek-v4-flash", "high")


def test_tui_app_with_store_persists_session_and_usage():
    """TUI 装配 store 后:会话落库且 usage 可读(/status 用量显示前提)。

    回归(cost-transparency):run_tui 未传 store 时 session._store 为 None,
    usage 无落库点、/status 显示「用量: (无)」。store 注入后本轮 usage
    落库并经 session.usage 读取到聚合值。
    """
    from codeagent.session.store import MemoryStore

    store = MemoryStore()
    import asyncio

    session = None
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(
            usage={
                "input_tokens": 100,
                "output_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 60},
            },
            response="回复",
        )
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend(), store=store)
        # _LazyConfig 首次 run 才装配模型客户端:run 必须在 mock 作用域内。
        session = app._manager.current
        assert session is not None
        asyncio.run(session.run("hi"))
    # 首轮成功后会话文件才落盘。
    assert store.get(session.session_id) is not None
    # usage 落库并经会话读取
    total = session.usage
    assert total.input_tokens == 100
    assert total.output_tokens == 20
    assert total.cached_tokens == 60


def test_create_tui_app_without_api_key_starts_lazy():
    """TUI 首启无 API key:不崩溃,端口/摘要器延迟到首次使用(回归:M-7)。

    原实现急切构造两个 LLM 客户端(摘要器 + 会话端口),缺 key 抛 ValueError
    穿透 run_tui,/login 首启流(鸡生蛋)不可达;延迟后 /login 写回 .env
    (create_llm 每次重读配置)自然生效。
    """
    from codeagent.app.container import _LazyConfig, _LazySummarizer, create_tui_app

    app = create_tui_app(provider="deepseek", backend=_StubBackend())
    assert isinstance(app._manager._config, _LazyConfig)
    assert isinstance(app._manager._summarizer, _LazySummarizer)
    assert app._manager._config._real is None  # 尚未装配:首次对话才构造
    assert app._manager._summarizer._real is None  # 首次 /compact 才构造


def test_save_key_unknown_provider_raises(tmp_path, monkeypatch):
    """save_key 对未知 provider 抛 ValueError(视图就地提示)。"""
    from codeagent.app import config as app_config

    monkeypatch.setattr(app_config, "CONFIG_ENV_FILE", tmp_path / ".env")
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend())
    import pytest

    with pytest.raises(ValueError):
        app._save_key("nosuch", "sk-x")


def test_create_tui_app_injects_configured_providers(tmp_path, monkeypatch):
    """configured_providers 从 .env 解析:仅非空 key 的 provider 进入登录 ✓ 集。"""
    from codeagent.app import config as app_config

    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=sk-1\nGLM_API_KEY=\nKIMI_API_KEY=\"sk-2\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "CONFIG_ENV_FILE", env_file)
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend())
    assert app._configured_providers == {"deepseek", "kimi"}
    # 登录选择器候选 = provider 全表
    assert app._candidates["login"] == app._candidates["provider"]


# -- usage 归一(cost-transparency)--------------------------------------------


def test_usage_of_openai_cached_tokens():
    """归一兼容 OpenAI 口径:缓存命中取 prompt_tokens_details.cached_tokens。"""
    from codeagent.app.container import _usage_of

    norm = _usage_of(
        {
            "prompt_tokens": 100,
            "completion_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 60},
            "output_token_details": {"reasoning": 5},
        }
    )
    assert norm == {
        "input_tokens": 100,
        "output_tokens": 30,
        "reasoning_tokens": 5,
        "cached_tokens": 60,
    }


def test_usage_of_vendor_cached_tokens():
    """归一兼容供应商口径:prompt_cache_hit_tokens 兜底缓存命中。"""
    from codeagent.app.container import _usage_of

    norm = _usage_of(
        {
            "input_tokens": 200,
            "output_tokens": 40,
            "prompt_cache_hit_tokens": 120,
        }
    )
    assert norm["cached_tokens"] == 120
    assert norm["reasoning_tokens"] == 0


def test_usage_of_missing_cached_defaults_zero():
    """双字段缺失:缓存命中兜底 0;reasoning 兜底 0;空 usage 返回 None。"""
    from codeagent.app.container import _usage_of

    norm = _usage_of({"prompt_tokens": 50, "completion_tokens": 10})
    assert norm == {
        "input_tokens": 50,
        "output_tokens": 10,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
    }
    assert _usage_of(None) is None
    assert _usage_of({}) is None


def test_config_append_mcp_tools(tmp_path, monkeypatch):
    """组合根装配:用户级 mcp.json → MCP 工具追加到内建工具之后(命名前缀)。"""
    monkeypatch.chdir(tmp_path)
    import json
    import sys

    mock_server = str(Path(__file__).parent / "mcp" / "mock_server.py")
    (tmp_path / ".codeagent").mkdir(exist_ok=True)
    (tmp_path / ".codeagent" / "mcp.json").write_text(
        json.dumps({"servers": [{"name": "mock", "command": sys.executable, "args": [mock_server]}]}),
        encoding="utf-8",
    )
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config

        ports = create_agent_config()
    names = [t.name for t in ports.tools]
    assert names[:8] == ["read", "write", "edit", "bash", "grep", "find", "ls", "skill"]
    assert "mcp__mock__echo" in names and "mcp__mock__fail" in names
    tool = next(t for t in ports.tools if t.name == "mcp__mock__echo")
    assert "echo:" in tool.invoke(tool.Args(text="hi"))
    from codeagent.tools.mcp.loader import close_mcp_tools

    close_mcp_tools(ports.tools)
