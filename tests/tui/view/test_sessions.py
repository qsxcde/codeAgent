"""TUI view sessions behavior tests."""

from tests.tui.view.fixtures import *  # noqa: F401,F403


def test_session_switch_refreshes_skill_registry_and_diagnostics():
    """切换会话后 TUI 应重读 Adapter/Registry 视图，而非保留启动快照。"""
    backend = StubBackend()
    manager = FakeManager()
    refreshed = []

    def refresh_skills():
        refreshed.append(True)
        return ([
            SimpleNamespace(
                name="using-superpowers",
                description="bootstrap",
                path="/pkg/using-superpowers/SKILL.md",
                package_id="superpowers",
                package_version="6.3.0",
                package_scope="user",
                bootstrap=True,
            )
        ], ["package_reload: ok"])

    app = TuiApp(
        manager,
        backend,
        skills=([], []),
        refresh_skills=refresh_skills,
    )
    manager.create()
    app._cmd_sessions(Command("sessions", ("new",), "new"))

    assert refreshed
    assert app._skills_by_name["using-superpowers"].package_id == "superpowers"
    assert app._skill_diagnostics == ["package_reload: ok"]



async def test_large_restore_drops_result_after_session_switch(monkeypatch):
    app, _, manager = _make_app()
    session = manager.current
    session.history = [Message(role="user", content=f"old-{i}") for i in range(1001)]
    calls = 0

    async def fake_to_thread(fn, *args):
        nonlocal calls
        calls += 1
        result = fn(*args)
        if calls == 2:
            manager.create()
        return result

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def scenario() -> None:
        await app._restore_large_session(session)

    await (scenario())

    assert not any("old-" in line for line in app.model.transcript.all_lines(80))



def test_fork_command_dispatches_and_feedback():
    """/fork → manager.fork(缺省最近用户消息),反馈含新会话 id 与原会话保留提示。"""
    app, backend, manager = _make_app()
    current_id = manager.current.session_id
    backend.submit("/fork")
    assert manager.fork_calls == [(current_id, None)]
    text = _rendered_text(app, backend)
    assert "已分叉会话" in text
    assert "重新开始" in text  # 反馈含分叉点语义(换行后短语仍可断言)
    assert "文件保持当前状态" in text



def test_fork_command_with_message_id():
    """/fork <message-id> → 显式分叉点传给 manager。"""
    app, backend, manager = _make_app()
    before_id = manager.current.session_id
    backend.submit("/fork msg-123")
    assert manager.fork_calls == [(before_id, "msg-123")]



def test_fork_command_error_shown_inline():
    """/fork 非法分叉点 → ValueError 就地提示,不崩溃。"""
    backend = StubBackend()

    class BoomManager(FakeManager):
        def fork(self, session_id, message_id=None):
            raise ValueError("分叉点必须是 user 消息: msg-x")

    app = TuiApp(BoomManager(), backend)
    backend.on_submit(app._submit)
    backend.submit("/fork msg-x")
    text = _rendered_text(app, backend)
    assert "分叉点必须是 user 消息" in text



def test_status_command_shows_session_info():
    """/status → 会话 id / 运行态 / 模型。"""
    app, backend, manager = _make_app()
    app.model.status.model = "deepseek-v4-flash"
    backend.submit("/status")
    text = _rendered_text(app, backend)
    assert manager.current.session_id in text
    assert "空闲" in text
    assert "deepseek-v4-flash" in text



def test_sessions_list_switch_and_new():
    """/sessions:列表 / <id> 切换 / new 新建 / recent 恢复最近。"""
    app, backend, manager = _make_app()
    first = manager.current

    backend.submit("/sessions list")
    text = _rendered_text(app, backend)
    assert "会话列表:" in text and first.session_id in text

    backend.submit("/sessions new")
    assert manager.current is not first

    backend.submit(f"/sessions {first.session_id}")
    assert manager.current is first
    text = _rendered_text(app, backend)
    assert "已切换到会话" in text

    backend.submit("/sessions ghost")
    text = _rendered_text(app, backend)
    assert "会话不存在" in text



def test_switching_session_hydrates_transcript_and_context_status():
    """切换会话会替换 transcript,并同步目标会话的上下文占用。"""
    app, backend, manager = _make_app()
    first = manager.current
    first.history = [Message(role="user", content="之前的问题"), Message(role="assistant", content="之前的回答")]
    first.context_tokens = 12_400
    first.context_window = 128_000
    other = manager.create()
    other.history = [Message(role="user", content="另一个问题"), Message(role="assistant", content="另一个回答")]
    other.context_tokens = 2_000
    other.context_window = 32_000

    backend.submit(f"/sessions {other.session_id}")
    text = _rendered_text(app, backend)
    assert "另一个问题" in text and "之前的问题" not in text
    assert app.model.status.context_tokens == 2_000
    assert app.model.status.context_window == 32_000



def test_sessions_recent_restores_last_session():
    """/sessions recent → 恢复最近会话(continue_recent);无会话时新建。"""
    app, backend, manager = _make_app()
    first = manager.current
    backend.submit("/sessions new")
    assert manager.current is not first
    backend.submit("/sessions recent")
    # continue_recent 取最近创建(时间升序末位)= first 之后的会话。
    assert manager.current is not first
    text = _rendered_text(app, backend)
    assert "已恢复最近会话" in text



def test_sessions_no_args_opens_inline_picker():
    """/sessions 无参 → 交互式选择器(命令名确认后弹会话候选浮层)。"""
    app, backend, manager = _make_app()
    backend.submit("/sessions")
    # 无参走 _open_inline_picker("sessions"):输入框填入 "/sessions " 触发候选。
    assert backend.input_texts[-1] == "/sessions "
    # 输入变更 → 候选 = 会话 id 列表
    backend.input_changed("/sessions ")
    assert app._suggestion_kind == "value"
    assert manager.current.session_id in app._suggestions



def test_sessions_picker_confirm_switches_session():
    """/sessions 选择器值确认 → 切换到所选会话(订阅跟随既有)。"""
    app, backend, manager = _make_app()
    first = manager.current
    backend.submit("/sessions new")
    other = manager.current
    backend.submit("/sessions")
    backend.input_changed("/sessions ")
    # 选中 first(历史会话)→ 确认切换
    app._suggestions = [first.session_id, other.session_id]
    app._suggestion_index = 0
    app._on_suggestion_confirm()
    assert manager.current is first
    text = _rendered_text(app, backend)
    assert "已切换到会话" in text



def test_sessions_picker_empty_state():
    """/sessions 无会话时选择器显示空态提示(不切换)。"""
    app, backend, manager = _make_app()
    manager.sessions = []  # 无任何历史会话
    manager.current = None
    backend.submit("/sessions")
    text = _rendered_text(app, backend)
    assert "暂无历史会话" in text



def test_tree_command_shows_fork_chain():
    """/tree → 展示 fork 链树(缩进 + 分支字符,含标题与 id)。"""
    app, backend, manager = _make_forked_manager()
    backend.submit("/tree")
    text = _rendered_text(app, backend)
    assert "会话树:" in text
    root = manager.current
    assert root.session_id in text
    # 分支 B 以缩进行展示于 A 下(含分支字符)。
    branch = manager.list()[-1]
    assert "├─" in text or "└─" in text
    assert branch.title in text



def test_tree_command_switches_session():
    """/tree <id> → 切换到指定会话(订阅跟随既有)。"""
    app, backend, manager = _make_forked_manager()
    branch_id = manager.list()[-1].id
    root_id = manager.current.session_id
    backend.submit(f"/tree {branch_id}")
    assert manager.current.session_id == branch_id
    backend.submit(f"/tree {root_id}")
    assert manager.current.session_id == root_id



def test_tree_command_unknown_session():
    """/tree <id> 会话不存在 → 就地报错,不切换。"""
    app, backend, manager = _make_forked_manager()
    before = manager.current
    backend.submit("/tree ghost")
    text = _rendered_text(app, backend)
    assert "会话不存在" in text
    assert manager.current is before



def test_tree_command_empty_state():
    """/tree 无会话 → 空态提示。"""
    app, backend, manager = _make_app()
    manager.sessions = []
    manager.current = None
    backend.submit("/tree")
    text = _rendered_text(app, backend)
    assert "(暂无会话)" in text



def test_sessions_list_shows_tree_indentation():
    """/sessions list → 父子缩进展示(子分支缩进于父下),孤儿平级。"""
    app, backend, manager = _make_forked_manager()
    backend.submit("/sessions list")
    text = _rendered_text(app, backend)
    assert "会话列表:" in text
    assert "├─" in text or "└─" in text
    # 根与分支标题均可见(树渲染用 FakeRef.title)。
    refs = manager.list()
    root_ref = refs[0]
    branch_ref = refs[-1]
    assert root_ref.title in text
    assert branch_ref.title in text

