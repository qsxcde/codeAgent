"""TUI view status behavior tests."""

from tests.tui.view.fixtures import *  # noqa: F401,F403


def test_status_usage_formatter_is_independent_of_command_dispatch() -> None:
    """用量格式化可脱离命令协调器测试，避免状态展示耦合命令分派。"""
    try:
        from codeagent.app.tui.commands.status import TuiStatusCommandCoordinator
    except ImportError:
        TuiStatusCommandCoordinator = None

    assert TuiStatusCommandCoordinator is not None
    assert TuiStatusCommandCoordinator._usage_line(None) == "(无)"


def test_context_command_shows_full_diagnostics_without_running_session() -> None:
    from codeagent.core.context.budget import ContextBudgetSnapshot
    from codeagent.core.context.diagnostics import ContextDiagnostics

    app, backend, manager = _make_app()
    manager.current.context_diagnostics = ContextDiagnostics.from_budget(
        ContextBudgetSnapshot(
            context_window=20_000,
            output_reserve=1_000,
            reserve_tokens=500,
            input_budget=18_500,
            system_prompt_tokens=100,
            tool_definitions_tokens=200,
            conversation_tokens=2_000,
            tool_result_tokens=300,
            input_tokens=2_600,
            headroom=15_900,
            status="estimate",
            window_source="catalog",
        ),
        model_id="demo",
    )
    before = (list(manager.current.run_texts), list(manager.current.history))

    backend.submit("/context")

    text = "\n".join(app.model.transcript.all_lines(120))
    assert "上下文诊断:" in text
    assert "窗口: 20,000" in text
    assert "system_prompt: 100" in text
    assert (manager.current.run_texts, manager.current.history) == before


async def test_footer_rich_line_seeded_and_passed():
    """装配数据(model/effort/cwd)经注入进状态栏并以富样式传给后端(design D5)。"""
    backend = StubBackend()
    manager = FakeManager()
    app = TuiApp(
        manager,
        backend,
        footer=FooterInfo(
            model="qwen3.8-max",
            effort="high",
            cwd="/workspace",
        ),
    )
    backend.on_resize(app._schedule_render)

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)

    await (_run())
    assert backend.statuses, "状态栏未渲染"
    plain = "".join(s.text for s in backend.statuses[-1])
    assert plain.startswith("  qwen3.8-m")
    assert "│" in plain
    # 状态栏注入模型名与工作目录(回归:此前 status.model 无注入点)
    assert app.model.status.model == "qwen3.8-max"
    assert app.model.status.cwd == "/workspace"



def test_context_usage_is_synced_to_footer_status():
    """最近一次请求的上下文占用会同步到状态栏右侧。"""
    backend = StubBackend()
    session = FakeSession()
    session.context_tokens = 12_400
    session.context_window = 128_000
    app = TuiApp(FakeManager(session), backend)

    app._flush_render()

    plain = "".join(span.text for span in backend.statuses[-1])
    assert "12.4k/128k" in plain
    assert "▱" in plain
    assert app.model.status.context_tokens == 12_400
    assert app.model.status.context_window == 128_000



def test_status_command_includes_runtime_and_render_diagnostics():
    app, backend, _ = _make_app()
    app.model.apply(
        AgentEvent(
            EventType.ERROR,
            payload="模型不可用",
            metadata={
                "error_code": "provider_unavailable",
                "retryable": True,
                "side_effect_state": "none",
            },
        )
    )
    backend.submit("/status")
    text = "\n".join(app.model.transcript.all_lines(120))
    assert "阶段: 失败" in text
    assert "错误码: provider_unavailable" in text
    assert "可重试: 是" in text
    assert "渲染:" in text
    assert "输出:" in text



def test_status_shows_usage_line_with_cache_hit():
    """/status → 用量行:输入/输出(含推理)/缓存命中率(约,含原始计数)。"""
    app, backend, manager = _make_app()
    manager.current.usage = UsageStats(
        input_tokens=1000, output_tokens=30, reasoning_tokens=20, cached_tokens=400
    )
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "用量: 输入 1000 · 输出 50 · 缓存命中约 40.0% (400/1000)" in text



def test_status_shows_usage_empty_state():
    """/status → 无用量记录时显示空态,不展示误导性数值。"""
    app, backend, manager = _make_app()
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "用量: (无)" in text
    assert "缓存命中" not in text



def test_status_usage_cache_ratio_clamped():
    """/status → 缓存命中率钳制:命中 > 输入时显示 100%(不超界误导)。"""
    app, backend, manager = _make_app()
    manager.current.usage = UsageStats(input_tokens=100, cached_tokens=300)
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "缓存命中约 100.0% (300/100)" in text



def test_config_command_without_args_shows_usage():
    """/provider 无参数 → 用法提示,不触发热切换。"""
    calls: list = []
    backend = StubBackend()
    app = TuiApp(
        FakeManager(),
        backend,
        rebuild_ports=lambda p, m, e: (calls.append(1), ("", ""))[1],
    )
    backend.on_submit(app._submit)
    backend.submit("/provider")
    text = _rendered_text(app, backend)
    assert "/provider <name>" in text
    assert calls == []



def test_status_shows_agents_sources_when_injected():
    """/status:注入来源列表 → 展示上下文文件(加载结果可见)。"""
    backend = StubBackend()
    app = TuiApp(
        FakeManager(),
        backend,
        agents_sources=["/global/AGENTS.md", "/proj/AGENTS.md"],
    )
    backend.on_submit(app._submit)
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "上下文文件:" in text
    assert "/global/AGENTS.md" in text
    assert "/proj/AGENTS.md" in text



def test_status_without_sources_shows_none():
    """/status:未注入来源 → 明确显示 (无)。"""
    app, backend, _ = _make_app()
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "上下文文件: (无)" in text



def test_picker_fallback_usage_hint_without_rebuild_ports():
    """候选缺失 / 未注入热切换 → 回退用法提示,不填输入框。"""
    app, backend, _ = _make_app()  # 无 rebuild_ports、无候选
    backend.submit("/model")
    assert backend.input_texts == []
    assert "/model <model" in _rendered_text(app, backend)



def test_status_shows_skills_and_diagnostics():
    """/status → 技能列表 + 加载诊断可见。"""
    diags = ["shadowed: project 技能 'fmt' 被更高优先级遮蔽", "parse_failed: xxx"]
    app, backend, _ = _make_skills_app(_sample_skills(), diags)
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "技能:" in text
    assert "fmt — 格式化代码。" in text
    assert "技能诊断:" in text
    assert "shadowed" in text and "parse_failed" in text



def test_status_shows_package_and_bootstrap_metadata():
    """/status 显示 Package 来源、revision 和 Bootstrap 状态。"""
    from codeagent.app.skills.models import Skill

    skill = Skill(
        "using-superpowers",
        "启动引导。",
        "/packages/superpowers/skills/using-superpowers/SKILL.md",
        "引导正文",
        package_id="superpowers",
        package_version="6.3.0",
        package_scope="user",
        bootstrap=True,
    )
    app, backend, _ = _make_skills_app([skill])
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "Bootstrap: using-superpowers" in text
    assert "Package: superpowers@6.3.0 (user)" in text



def test_status_shows_mcp_diagnostics():
    """/status → MCP 装配诊断可见(mcp-client:加载结果可见可断言)。"""
    app, backend, _ = _make_skills_app([], [])
    app._mcp_diagnostics = ["start_failed: MCP server 'bad' 启动失败: x"]
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "MCP:" in text
    assert "start_failed" in text and "bad" in text



def test_status_without_mcp_diagnostics():
    """/status → 无 MCP 诊断时无 MCP 区。"""
    app, backend, _ = _make_app()
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert "MCP:" not in text
