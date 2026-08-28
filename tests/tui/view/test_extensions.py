"""TUI view extensions behavior tests."""

import threading

from tests.tui.view.fixtures import *  # noqa: F401,F403


def test_skills_package_subcommand_is_forwarded_to_composition_root():
    """/skills Package 子命令由组合根执行，TUI 仅刷新并展示结果。"""
    backend = StubBackend()
    manager = FakeManager()
    calls = []

    def package_action(action, args):
        calls.append((action, args))
        return "已安装 Package demo"

    app = TuiApp(manager, backend, package_action=package_action)
    app._cmd_skills(Command("skills", ("install", "./demo"), "install ./demo"))

    assert calls == [("install", ("./demo",))]
    assert "已安装 Package demo" in "\n".join(app.model.transcript.all_lines(120))


async def test_package_action_runs_off_the_tui_event_loop():
    started = threading.Event()
    release = threading.Event()

    def package_action(action, args):
        started.set()
        assert release.wait(1)
        return "安装完成"

    app = TuiApp(FakeManager(), StubBackend(), package_action=package_action)
    app._cmd_skills(Command("skills", ("install", "./demo"), "install ./demo"))

    assert await asyncio.to_thread(started.wait, 1)
    task = app._package_task
    assert task is not None and not task.done()
    release.set()
    await task
    assert "安装完成" in "\n".join(app.model.transcript.all_lines(120))



def test_submit_is_gated_during_restore_and_compaction():
    app, backend, manager = _make_app()
    app.model.apply(AgentEvent(EventType.RESTORE_STARTED))
    backend.submit("普通消息")
    assert manager.current.run_texts == []
    app.model.apply(AgentEvent(EventType.RESTORE_FINISHED))
    app.model.apply(AgentEvent(EventType.COMPACTION_STARTED))
    backend.submit("另一条消息")
    assert manager.current.run_texts == []



async def test_large_restore_never_hydrates_live_model_in_worker(monkeypatch):
    app, _, manager = _make_app()
    session = manager.current
    session.history = [Message(role="user", content=f"m-{i}") for i in range(1001)]
    calls: list[Any] = []

    async def fake_to_thread(fn, *args):
        calls.append(fn)
        return fn(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def scenario() -> None:
        await app._restore_large_session(session)

    await (scenario())

    assert calls
    assert all(getattr(fn, "__self__", None) is not app.model for fn in calls)



def test_config_commands_use_rebuild_ports():
    """/provider /model /effort 经注入回调热切换,状态栏同步更新。"""
    calls: list[tuple] = []
    backend = StubBackend()
    manager = FakeManager()

    def rebuild(provider, model, effort):
        calls.append((provider, model, effort))
        return "m2", "high"

    app = TuiApp(manager, backend, rebuild_ports=rebuild)
    backend.on_submit(app._submit)

    backend.submit("/provider deepseek")
    assert calls[-1] == ("deepseek", None, None)
    assert app.model.status.model == "m2" and app.model.status.effort == "high"

    backend.submit("/model deepseek-v4:high")
    assert calls[-1] == (None, "deepseek-v4:high", None)

    backend.submit("/effort low")
    assert calls[-1] == (None, None, "low")



def test_config_command_invalid_provider_shows_error():
    """/provider 未知值 → 回调 ValueError 就地提示(NFR-U7 容错)。"""
    backend = StubBackend()

    def rebuild(provider, model, effort):
        raise ValueError("未知的 provider: 'nope'")

    app = TuiApp(FakeManager(), backend, rebuild_ports=rebuild)
    backend.on_submit(app._submit)
    backend.submit("/provider nope")
    text = _rendered_text(app, backend)
    assert "未知的 provider" in text



def test_input_changed_shows_command_suggestions():
    """/ + 前缀 → 浮层展示模糊匹配的命令建议。"""
    app, backend, _ = _make_app()
    backend.input_changed("/st")
    assert app._suggestions  # 命中 status/sessions 等
    assert app._suggestions[0] == "status"  # 精确前缀优先
    # 浮层渲染为样式标签行
    lines = backend.suggestion_lines[-1]
    assert lines and "/status" in lines[0][1].text



def test_input_changed_plain_text_hides_suggestions():
    """普通文本输入 → 无建议、浮层隐藏。"""
    app, backend, _ = _make_app()
    backend.input_changed("你好")
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []



def test_suggestion_navigate_cycles_and_confirm_fills():
    """↑/↓ 循环选择,确认后填入输入框并收起浮层。"""
    app, backend, _ = _make_app()
    backend.input_changed("/s")
    total = len(app._suggestions)
    backend.suggestion_nav(1)
    assert app._suggestion_index == 1
    backend.suggestion_nav(-1)
    assert app._suggestion_index == 0
    backend.suggestion_nav(-1)  # 循环到头
    assert app._suggestion_index == total - 1
    selected = app._suggestions[total - 1]
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == f"/{selected}"
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []



def test_provider_selector_candidates_injected():
    """选择器候选经组合根注入:/provider 空格后按候选模糊匹配。"""
    app, backend, _ = _make_app()
    app._candidates = {"provider": ["deepseek", "openai", "qwen"], "model": {}, "effort": []}
    backend.input_changed("/provider deep")
    names = list(app._suggestions)
    assert names == ["deepseek"]
    backend.input_changed("/provider o")
    assert app._suggestions[0] == "openai"
    # 非选择器命令不触发候选
    backend.input_changed("/clear x")
    assert app._suggestions == []



def test_suggestion_window_fixed_height_and_scrolls():
    """补全浮层固定窗口:候选多于窗口时渲染行数 = 窗口高,高亮居中跟随。

    - 首屏:渲染 _SUGGESTION_WINDOW 行(非全量),高亮第 1 条;
    - 下移:高亮进入窗口中部后,窗口起点跟随滚动;
    - 末条:窗口底部对齐,高亮可见(不被顶出窗口)。
    """
    from codeagent.app.tui.view import _SUGGESTION_WINDOW

    app, backend, _ = _make_app()
    # 用注册表全量命令(14 条 > 窗口 9)验证固定窗口滚动。
    from codeagent.app.tui.commands import default_registry

    names = list(default_registry())
    assert len(names) > _SUGGESTION_WINDOW  # 前提:候选多于窗口
    app._suggestions = list(names)
    app._suggestion_index = 0
    app._suggestion_kind = "command"
    app._render_suggestions()
    rendered = backend.suggestion_lines[-1]
    assert len(rendered) == _SUGGESTION_WINDOW  # 固定窗口高,非 14 行全量
    # 首行 = 首候选且高亮
    first_text = "".join(span.text for span in rendered[0])
    assert names[0] in first_text and "›" in first_text

    # 下移 10 次:高亮进入中部后窗口起点跟随滚动(可见窗口不再从 0 起)。
    for _ in range(10):
        app._on_suggestion_navigate(1)
    rendered = backend.suggestion_lines[-1]
    first_text = "".join(span.text for span in rendered[0])
    assert names[0] not in first_text  # 窗口已滚动,首行不是首候选

    # 末条:窗口底部对齐,末候选高亮可见(不被顶出窗口)。
    app._suggestion_index = len(names) - 1
    app._render_suggestions()
    rendered = backend.suggestion_lines[-1]
    last_text = "".join(span.text for span in rendered[-1])
    assert names[-1] in last_text and "›" in last_text



async def test_compact_command_dispatches_and_feedback():
    """/compact → 会话 compact 异步执行,完成后反馈压缩结果。"""
    backend = StubBackend()

    compact_done = asyncio.Event()

    class CompactSession(FakeSession):
        async def compact(self):
            compact_done.set()
            return True

    class CompactManager(FakeManager):
        def __init__(self):
            super().__init__(session=CompactSession())

    app = TuiApp(CompactManager(), backend)
    backend.on_submit(app._submit)
    backend.on_resize(app._schedule_render)

    async def _run() -> None:
        feedback_rendered = asyncio.Event()
        original_render = backend.render

        def render(lines) -> None:
            original_render(lines)
            if "已压缩" in "".join(rich_to_plain(lines)):
                feedback_rendered.set()

        backend.render = render
        backend.resize()
        backend.submit("/compact")
        await asyncio.wait_for(compact_done.wait(), timeout=1.0)
        await asyncio.wait_for(feedback_rendered.wait(), timeout=1.0)

    await (_run())



def test_compact_command_unavailable_inline():
    """/compact 会话不支持压缩(无 compact 方法)→ 就地提示。"""
    app, backend, _ = _make_app()
    backend.submit("/compact")
    text = _rendered_text(app, backend)
    assert "不可用" in text



def test_bare_model_command_opens_inline_strip_scoped_to_provider():
    """无参 /model → 输入框填 "/model " 弹值候选浮层;仅列当前 provider 的模型,
    当前生效项 ✓,首行默认 › 选中。"""
    app, backend, _ = _make_picker_app()
    backend.submit("/model")
    assert backend.input_texts[-1] == "/model "
    backend.input_changed("/model ")  # textual 异步变更通知
    assert app._suggestions == ["m-a", "m-b"]  # 仅 p-a 的模型,不含 p-b 的 m-x
    rows = _strip_rows(backend)
    assert any("✓" in r and "m-a" in r for r in rows)
    assert rows[0].startswith("› ")



def test_inline_picker_filter_and_navigate_cycles():
    """键入模糊过滤并复位选中;↑↓ 循环导航(复用建议条既有交互)。"""
    app, backend, _ = _make_picker_app()
    backend.submit("/effort")
    backend.input_changed("/effort ")
    assert app._suggestions == ["low", "medium", "high"]
    backend.suggestion_nav(1)
    assert app._suggestion_index == 1
    backend.suggestion_nav(-2)  # 1 - 2 → 循环到尾
    assert app._suggestion_index == 2
    backend.input_changed("/effort med")
    assert app._suggestions == ["medium"]
    assert app._suggestion_index == 0



def test_inline_picker_confirm_applies_and_closes():
    """Enter → rebuild_ports 生效(provider 锁定当前值)、浮层收起、输入清空、状态栏更新。"""
    app, backend, calls = _make_picker_app()
    backend.submit("/model")
    backend.input_changed("/model ")
    backend.suggestion_nav(1)  # 选中 m-b
    backend.suggestion_confirm()
    assert calls == [("p-a", "m-b", None)]
    assert backend.suggestion_lines[-1] == []
    assert backend.input_texts[-1] == ""
    assert app.model.status.model == "m-new"



def test_inline_picker_esc_dismisses_without_apply():
    """Esc → 浮层收起、输入清空,不触发热切换。"""
    app, backend, calls = _make_picker_app()
    backend.submit("/effort")
    backend.input_changed("/effort ")
    backend.interrupt()
    assert backend.suggestion_lines[-1] == []
    assert backend.input_texts[-1] == ""
    assert calls == []



def test_inline_picker_provider_confirm_updates_provider():
    """provider 浮层:✓ 取装配记录;确认后 _provider 更新,模型候选随 provider 切换。"""
    app, backend, calls = _make_picker_app()
    backend.submit("/provider")
    backend.input_changed("/provider ")
    rows = _strip_rows(backend)
    assert any("✓" in r and "p-a" in r for r in rows)
    backend.suggestion_nav(1)
    backend.suggestion_confirm()
    assert calls == [("p-b", None, None)]
    assert app._provider == "p-b"
    backend.input_changed("")  # 清空输入引发的异步通知(消费抑制位)
    backend.submit("/provider")  # 重开:✓ 移到 p-b
    backend.input_changed("/provider ")
    rows = _strip_rows(backend)
    assert any("✓" in r and "p-b" in r for r in rows)
    backend.input_changed("")  # 收起浮层(Esc 语义等价,直接走值语境取消)
    backend.submit("/model")  # 模型候选跟随新 provider
    backend.input_changed("/model ")
    assert app._suggestions == ["m-x"]



def test_suggestion_confirm_opens_inline_picker_for_picker_command():
    """命令建议确认:picker 命令(/mod → model)进入内联选择,条目含描述列。"""
    app, backend, _ = _make_picker_app()
    backend.input_changed("/mod")
    assert app._suggestions[0] == "model"  # 精确前缀优先(mcp 等模糊命中在后)
    row = "".join(s.text for s in backend.suggestion_lines[-1][0])
    assert "/model" in row and "—" in row
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/model "
    backend.input_changed("/model ")  # 异步通知弹值候选浮层
    assert app._suggestion_kind == "value"
    assert app._suggestions == ["m-a", "m-b"]



def test_suggestion_confirm_non_picker_still_fills_input():
    """非 picker 命令(/clear)建议确认 → 保持填入输入框原行为。"""
    app, backend, _ = _make_picker_app()
    backend.input_changed("/cle")
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/clear"



def test_login_without_args_opens_picker():
    """无参 /login → 输入框填 "/login " 弹 provider 候选浮层(复用选择器)。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login")
    assert backend.input_texts[-1] == "/login "
    backend.input_changed("/login ")
    assert app._suggestions == ["deepseek", "glm", "fake"]



def test_login_with_provider_enters_mask_mode():
    """带参 /login deepseek → 掩码输入态:提示文案 + 掩码开启。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login deepseek")
    assert app._login_pending == "deepseek"
    assert backend.mask_calls == [True]
    assert backend.placeholders[-1] == "输入 DEEPSEEK_API_KEY,Enter 保存 / Esc 取消"



def test_login_fake_skips_input():
    """/login fake → 提示无需密钥,不进入掩码输入态。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login fake")
    assert app._login_pending is None
    assert backend.mask_calls == []



def test_login_unknown_provider_rejected():
    """/login <未知> → 就地提示,不进入输入态。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login nosuch")
    assert app._login_pending is None
    assert backend.mask_calls == []



def test_login_picker_value_confirm_enters_mask():
    """登录选择器值确认 → 进入掩码输入态(非配置切换)。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login")
    backend.input_changed("/login ")
    backend.suggestion_confirm()  # 首项 deepseek
    assert app._login_pending == "deepseek"
    assert backend.mask_calls == [True]



def test_login_picker_marks_configured_providers():
    """登录选择器:已配置 key 的 provider 打 ✓(组合根注入 configured_providers)。"""
    app, backend, _ = _make_login_app(configured=["glm"])
    backend.submit("/login")
    backend.input_changed("/login ")
    rows = _strip_rows(backend)
    assert any("✓" in r and "glm" in r for r in rows)
    assert not any("✓" in r and "deepseek" in r for r in rows)



def test_login_empty_key_stays_in_input():
    """空密钥提交 → 提示并停留输入态(不退出掩码、不保存)。"""
    app, backend, saved = _make_login_app()
    backend.submit("/login deepseek")
    backend.submit("")
    assert app._login_pending == "deepseek"  # 仍在登录态
    assert backend.mask_calls == [True]  # 掩码未解除
    assert saved == []



def test_login_esc_cancels_without_saving():
    """登录态 Esc → 取消输入,掩码解除,不保存任何内容。"""
    app, backend, saved = _make_login_app()
    backend.submit("/login deepseek")
    backend.interrupt()
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]
    assert saved == []



def test_login_save_success_switches_provider():
    """保存成功 → 写 .env(经注入回调)、状态栏更新、provider 与已配置集更新。"""
    app, backend, saved = _make_login_app()
    backend.submit("/login deepseek")
    backend.submit("sk-secret-1")
    assert saved == [("deepseek", "sk-secret-1")]
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]
    assert app._provider == "deepseek"
    assert app.model.status.model == "deepseek-v4-flash"
    assert "deepseek" in app._configured_providers
    assert "glm" not in app._configured_providers



def test_login_save_value_error_feedback():
    """保存抛 ValueError(未知 provider 等)→ 提示错误并退出输入态。"""
    def boom(provider: str, key: str) -> tuple[str, str]:
        raise ValueError(f"未知的 provider: {provider!r}")

    app, backend, saved = _make_login_app(save_fn=boom)
    backend.submit("/login deepseek")
    backend.submit("sk-x")
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]
    assert saved == [("deepseek", "sk-x")]  # 回调确被调用



def test_login_save_os_error_feedback():
    """保存抛 OSError(磁盘不可写等)→ 提示保存失败并退出输入态。"""
    def boom(provider: str, key: str) -> tuple[str, str]:
        raise OSError("disk full")

    app, backend, _ = _make_login_app(save_fn=boom)
    backend.submit("/login deepseek")
    backend.submit("sk-x")
    assert app._login_pending is None
    assert backend.mask_calls == [True, False]



def test_login_disables_suggestions():
    """登录态建议浮层禁用:输入变化不弹任何候选。"""
    app, backend, _ = _make_login_app()
    backend.submit("/login deepseek")
    backend.input_changed("/pro")
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []



def test_skills_command_lists_skills():
    """/skills 无参 → 紧凑分组列表，不重复展示路径和 Package 元数据。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.submit("/skills")
    text = _rendered_text(app, backend)
    assert "可用技能 (2)" in text
    assert "superpowers · 1" in text
    assert "本地技能 · 1" in text
    assert "brainstorming" in text and "fmt" in text
    assert "/packages/superpowers" not in text
    assert "Package: superpowers" not in text
    assert "应该被截断" not in text
    assert manager_run_texts(app) == []



def test_skills_info_shows_full_metadata_for_one_skill():
    """/skills info <name> → 详情页展示完整路径、Package 和版本。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.submit("/skills info brainstorming")
    text = _rendered_text(app, backend)

    assert "技能详情" in text
    assert "名称: brainstorming" in text
    assert "来源: /packages/superpowers/skills/brainstorming/SKILL.md" in text
    assert "Package: superpowers@6.3.0 (user)" in text



def test_skills_command_without_skills():
    """/skills 无技能 → 明确说明。"""
    app, backend, _ = _make_skills_app([])
    backend.submit("/skills")
    assert "技能: (无)" in _rendered_text(app, backend)



async def test_skills_command_loads_skill():
    """/skills <name> → 渲染块以标注技能名的消息进入会话并触发一轮回复。"""
    app, backend, manager = _make_skills_app(_sample_skills())

    async def _run() -> None:
        backend.submit("/skills fmt")
        await asyncio.sleep(0)

    await (_run())
    session = manager.current
    assert len(session.run_texts) == 1
    text = session.run_texts[0]
    assert "[用户手动加载技能: fmt]" in text
    assert '<skill name="fmt" location="/skills/fmt/SKILL.md">' in text
    assert "格式化正文" in text



def test_skills_command_unknown_skill():
    """/skills <未知名> → 明确错误并列出可用技能,不注入不运行。"""
    app, backend, manager = _make_skills_app(_sample_skills())
    backend.submit("/skills nope")
    text = _rendered_text(app, backend)
    assert "未知技能: nope" in text
    assert "fmt" in text and "brainstorming" in text
    assert manager.current.run_texts == []



def test_skills_suggestion_candidates():
    """/skills ␣ → 技能名模糊候选(输入框补全)。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.input_changed("/skills f")
    assert app._suggestions == ["fmt"]
    backend.input_changed("/skills ")
    assert set(app._suggestions) == {"fmt", "brainstorming"}



async def test_skills_suggestion_confirm_fills_command():
    """技能候选确认 → 填入 /skills <name>,再次 Enter 即加载。"""
    app, backend, _ = _make_skills_app(_sample_skills())
    backend.input_changed("/skills br")
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/skills brainstorming"
    assert app._suggestions == []
    # 再次提交 → 执行手动加载
    async def _run() -> None:
        backend.submit("/skills brainstorming")
        await asyncio.sleep(0)

    await (_run())
    assert "[用户手动加载技能: brainstorming]" in app._manager.current.run_texts[0]



def test_mcp_command_groups_tools_by_server():
    """/mcp → 按 server 分组列出工具(对齐 Claude /mcp 的 server 维度视图)。"""
    app, backend, manager = _make_app()
    manager.tools = [
        SimpleNamespace(name="read"),
        SimpleNamespace(name="mcp__github__list_issues"),
        SimpleNamespace(name="mcp__github__push"),
        SimpleNamespace(name="mcp__db__query"),
    ]
    app._mcp_diagnostics = ["start_failed: MCP server 'bad' 启动失败: x"]
    backend.submit("/mcp")
    text = _rendered_text(app, backend)
    assert "MCP server:" in text
    assert "github: list_issues, push" in text
    assert "db: query" in text
    assert "start_failed" in text



def test_mcp_command_without_servers():
    """/mcp → 未配置 server 时明确说明。"""
    app, backend, _ = _make_app()
    backend.submit("/mcp")
    assert "MCP: (未配置 server)" in _rendered_text(app, backend)

