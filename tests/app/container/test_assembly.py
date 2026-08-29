"""assembly behavior tests."""

from types import SimpleNamespace

from tests.app.container.fixtures import *  # noqa: F401,F403


def test_create_agent_config_returns_config():
    """用 fake provider 注入,零网络装配自研端口(模型端口 + 工具)。"""
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config
        from codeagent.core.orchestration.config import AgentLoopConfig

        config = create_agent_config()
    assert isinstance(config, AgentLoopConfig)
    assert len(config.tools) == 8
    assert config.model.model_id == "fake-model"
    assert [item.key for item in config.tool_capabilities.items] == [
        "platform",
        "shell",
        "process_tree_cleanup",
        "rg",
        "fd",
        "permissions",
    ]


def test_create_agent_config_passes_context_preflight_policy():
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_agent_config
        from codeagent.core import ContextPreflightConfig

        mock_llm.return_value = FakeClient(response="测试回复")
        policy = ContextPreflightConfig(warning_headroom_tokens=321)
        config = create_agent_config(
            provider="fake",
            uncertain_budget_policy="fail",
            context_preflight=policy,
        )

    assert config.context_preflight is policy
    assert config.uncertain_budget_policy == "fail"


def test_create_agent_config_injects_one_resource_limits_bundle():
    from types import SimpleNamespace

    from codeagent.tools.shared import ToolResourceLimits

    limits = ToolResourceLimits(max_concurrency=2, timeout=1.0, max_timeout=2.0)
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_agent_config

        mock_llm.return_value = FakeClient(response="测试回复")
        config = create_agent_config(provider="fake", resource_limits=limits)

    assert config.tool_resource_limits is limits
    assert config.tool_runtime.max_concurrency == 2
    assert config.tool_timeout == 1.0
    bash = next(tool._tool for tool in config.tools if tool.name == "bash")
    assert bash.resource_limits is limits
    del SimpleNamespace



def test_create_agent_session_returns_session():
    """create_agent_session 返回可订阅的 AgentSession。"""
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_session

        sess = create_agent_session()
    assert hasattr(sess, "run")
    assert hasattr(sess, "subscribe")
    assert hasattr(sess, "abort")
    assert hasattr(sess, "steer")



def test_create_tui_app_assembles_with_stub_backend():
    """create_tui_app 装配 session + backend,不依赖 textual(design D5)。"""
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
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
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
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
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.session.persistence import MemoryStore

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


async def test_tui_async_rebuild_waits_for_old_runtime_close():
    from unittest.mock import patch

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

    with patch(
        "codeagent.app.composition.model.selection.create_llm",
        side_effect=make_client,
    ):
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend())
        _ = app._manager.tools
        assert len(clients) == 1

        model_id, effort = await app._rebuild_ports_async(
            "fake", "fake-model:high", None
        )

    assert (model_id, effort) == ("fake-model", "high")
    assert clients[0].closed == 1
    assert clients[1].closed == 0



def test_rebuild_config_syncs_model_context_window():
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
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


def test_create_agent_config_binds_catalog_window_to_model_budget():
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_agent_config
        from codeagent.core.contracts.messages import Message

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("fake", {})["small-model"] = ModelSpec(
            id="small-model", context_window=32_000, max_tokens=2_000
        )
        config = create_agent_config(
            provider="fake", model="small-model", registry=registry
        )

    budget = config.model.describe_context_budget(
        [Message(role="user", content="hello")], []
    )

    assert budget.context_window == 32_000
    assert budget.output_reserve == 2_000
    assert budget.window_source == "catalog"


def test_create_agent_config_injects_model_capabilities():
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_agent_config

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("fake", {})["diagnostic-model"] = ModelSpec(
            id="diagnostic-model",
            reasoning=True,
            tool_calling=False,
            prompt_cache=True,
            context_window=32_000,
        )
        config = create_agent_config(
            provider="fake", model="diagnostic-model", registry=registry
        )

    capabilities = config.model_capabilities
    assert capabilities is config.model.capabilities
    assert capabilities.model == "diagnostic-model"
    assert capabilities.context_window == 32_000
    assert capabilities.window_source == "catalog"
    assert capabilities.reasoning is True
    assert capabilities.tool_calling is False
    assert capabilities.prompt_cache is True


def test_create_tui_app_injects_model_capabilities_and_refreshes_after_rebuild():
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_tui_app

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("fake", {}).update(
            {
                "first": ModelSpec(
                    id="first", reasoning=True, tool_calling=True, context_window=64_000
                ),
                "second": ModelSpec(
                    id="second", reasoning=False, prompt_cache=True, context_window=16_000
                ),
            }
        )
        app = create_tui_app(
            provider="fake", model="first", registry=registry, backend=_StubBackend()
        )

        assert app.model.status.model_capabilities.model == "first"
        assert app.model.status.model_capabilities.tool_calling is True
        model_id, effort = app._rebuild_ports("fake", "second", None)
        app._finish_config(model_id, effort)

    capabilities = app.model.status.model_capabilities
    assert capabilities.model == "second"
    assert capabilities.context_window == 16_000
    assert capabilities.reasoning is False
    assert capabilities.tool_calling is None
    assert capabilities.prompt_cache is True


def test_create_agent_config_keeps_tiny_catalog_window_budget_valid():
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_agent_config

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("fake", {})["tiny-model"] = ModelSpec(
            id="tiny-model", context_window=8_000
        )
        config = create_agent_config(
            provider="fake", model="tiny-model", registry=registry
        )

    budget = config.model.describe_context_budget([], [])

    assert budget.context_window == 8_000
    assert budget.output_reserve + budget.reserve_tokens <= 8_000


def test_create_tui_app_uses_provider_default_model_context_window():
    """TUI 初始未显式传 model 时,按 provider 默认模型读取窗口。"""
    with (
        patch("codeagent.app.composition.model.selection.create_llm") as mock_llm,
        patch(
            "codeagent.app.composition.model.factory._provider_config",
            return_value=SimpleNamespace(
                model="configured-model", reasoning_effort="high"
            ),
        ),
    ):
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_tui_app

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("deepseek", {})["configured-model"] = ModelSpec(
            id="configured-model", context_window=64_000
        )
        app = create_tui_app(
            provider="deepseek", registry=registry, backend=_StubBackend()
        )

    assert app._manager.current.context_window == 64_000


def test_create_agent_session_uses_model_context_window():
    """headless AgentSession 使用显式模型的上下文窗口,而非固定默认值。"""
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_agent_session

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("fake", {})["small-model"] = ModelSpec(
            id="small-model", context_window=32_000
        )
        session = create_agent_session(
            provider="fake", model="small-model", registry=registry
        )

    assert session.context_window == 32_000


def test_create_agent_session_uses_provider_default_context_window():
    """headless 未显式传 model 时,按 provider 默认模型读取窗口。"""
    with (
        patch("codeagent.app.composition.model.selection.create_llm") as mock_llm,
        patch(
            "codeagent.app.composition.model.factory._provider_config",
            return_value=SimpleNamespace(
                model="configured-model", reasoning_effort="high"
            ),
        ),
    ):
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.spec import ModelSpec
        from codeagent.ai.providers.fake import FakeClient
        from codeagent.app.container import create_agent_session

        mock_llm.return_value = FakeClient(response="测试回复")
        registry = ModelRegistry()
        registry._catalogs.setdefault("deepseek", {})["configured-model"] = ModelSpec(
            id="configured-model", context_window=64_000
        )
        with patch(
            "codeagent.app.composition.model.factory._get_default_registry",
            return_value=registry,
        ):
            session = create_agent_session(provider="deepseek")

    assert session.context_window == 64_000



def test_create_tui_app_injects_selector_candidates():
    """选择器候选经组合根注入(T-45):provider/model/effort 各一份。"""
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
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



def test_tui_app_gets_compaction_capable_manager():
    """create_tui_app 装配 Summarizer:/compact 可经 current 会话执行。"""
    from codeagent.app.container import create_tui_app
    from codeagent.app.tui.ports.backend import TuiBackend

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

    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        app = create_tui_app(backend=StubBackend())
    assert app._manager.current is not None
    assert app._manager._summarizer is not None  # /compact 可用



def test_create_tui_app_injects_save_key(tmp_path, monkeypatch):
    """组合根注入 save_key:/login 写 .env(<PREFIX>_API_KEY)并热切换。"""
    from codeagent.app import config as app_config

    env_file = tmp_path / ".codeagent" / ".env"
    monkeypatch.setattr(app_config, "CONFIG_ENV_FILE", env_file)
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
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
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
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
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_tui_app

        app = create_tui_app(provider="fake", backend=_StubBackend())
    assert app._configured_providers == {"deepseek", "kimi"}
    # 登录选择器候选 = provider 全表
    assert app._candidates["login"] == app._candidates["provider"]



def test_config_append_mcp_tools(tmp_path, monkeypatch):
    """组合根装配:用户级 mcp.json → MCP 工具追加到内建工具之后(命名前缀)。"""
    monkeypatch.chdir(tmp_path)
    import json
    import sys

    mock_server = str(Path(__file__).parents[2] / "mcp" / "mock_server.py")
    (tmp_path / ".codeagent").mkdir(exist_ok=True)
    (tmp_path / ".codeagent" / "mcp.json").write_text(
        json.dumps({"servers": [{"name": "mock", "command": sys.executable, "args": [mock_server]}]}),
        encoding="utf-8",
    )
    with patch("codeagent.app.composition.model.selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config
        from codeagent.core import AgentTool

        ports = create_agent_config()
    names = [t.name for t in ports.tools]
    assert all(isinstance(tool, AgentTool) for tool in ports.tools)
    assert names[:8] == ["read", "write", "edit", "bash", "grep", "find", "ls", "skill"]
    assert "mcp__mock__echo" in names and "mcp__mock__fail" in names
    import asyncio

    tool = next(t for t in ports.tools if t.name == "mcp__mock__echo")
    result = asyncio.run(tool.execute("mcp-1", {"text": "hi"}))
    assert "echo:" in result.content
    from codeagent.tools.mcp.loader import close_mcp_tools

    close_mcp_tools(ports.tools)
