"""model behavior tests."""

from tests.app.container.fixtures import *  # noqa: F401,F403


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



async def test_config_inject_system_prompt_with_agents(tmp_path, monkeypatch):
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
    await (_run_config(ports, "你好", emit=events.append))
    assert model.call_history
    first = model.call_history[0]["messages"][0]
    assert first["role"] == "system"
    assert "codeagent" in first["content"]  # 基础提示词
    assert "项目级指令" in first["content"]
    assert '<project_instructions path="' in first["content"]
    assert "全局指令" in first["content"]



async def test_system_prompt_only_once_and_hot_swap_stable(tmp_path, monkeypatch):
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
    history = await (_run_config(ports, "第一问", emit=events.append))
    await (_run_config(ports, "第二问", history=history, emit=events.append))
    for call in model.call_history:
        roles = [m["role"] for m in call["messages"]]
        assert roles.count("system") == 1  # 每轮恰好一条
        assert roles[0] == "system"



async def test_bootstrap_is_present_once_per_model_context_for_new_and_recovered_turns(tmp_path, monkeypatch):
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
    history = await (_run_config(ports, "第一问", history=history, emit=events.append))
    history = await (_run_config(ports, "第二问", history=history, emit=events.append))
    assert history
    for call in model.call_history:
        roles = [message["role"] for message in call["messages"]]
        assert roles.count("system") == 1
        assert BOOTSTRAP_TAG in call["messages"][0]["content"]



async def test_bootstrap_is_reinjected_after_context_compaction(tmp_path, monkeypatch):
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
        await (session.run(text))
    assert await (session.compact()) is True
    await (session.run("问4" * 40))
    assert BOOTSTRAP_TAG in model.call_history[-1]["messages"][0]["content"]



async def test_config_inject_skills_section_and_tool(tmp_path, monkeypatch):
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
    await (_run_config(ports, "你好", emit=events.append))
    first = model.call_history[0]["messages"][0]
    assert "<available_skills>" in first["content"]
    assert "- fmt: 格式化。 (来源:" in first["content"]
    assert "格式化正文" not in first["content"]  # 正文不预载
    skill_tool = next(t for t in ports.tools if getattr(t, "name", "") == "skill")
    out = skill_tool.invoke(skill_tool.Args(name="fmt"))
    assert "格式化正文" in out
    out = skill_tool.invoke(skill_tool.Args(name="nope"))
    assert "技能不存在" in out



async def test_session_with_summarizer_can_compact():
    """注入桩 Summarizer 的会话可压缩;压缩不可用(未注入)时明确报错。"""
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_session

        session = create_agent_session(summarizer=_StubSummarizer())
        assert await (session.compact()) is False  # 空历史:全保留,不压缩
        from codeagent.session import AgentSession

        plain = create_agent_session()
        with pytest.raises(ValueError, match="压缩不可用"):
            await (plain.compact())



async def test_tui_app_with_store_persists_session_and_usage():
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
        await (session.run("hi"))
    # 首轮成功后会话文件才落盘。
    assert store.get(session.session_id) is not None
    # usage 落库并经会话读取
    total = session.usage
    assert total.input_tokens == 100
    assert total.output_tokens == 20
    assert total.cached_tokens == 60



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

