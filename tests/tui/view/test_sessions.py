"""TUI view sessions behavior tests."""

from tests.tui.view.fixtures import *  # noqa: F401,F403

from codeagent.session.persistence import RecoveryDiagnostic, SessionRecoveryError, SessionRecoveryReport
from codeagent.app.tui.presentation.blocks import SubagentBlock


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


async def test_large_restore_moves_persisted_subagent_projection_with_history():
    app, _, manager = _make_app()
    session = manager.current
    session.history = [Message(role="user", content=f"old-{i}") for i in range(1001)]
    from codeagent.session.persistence import SubagentRunRecord

    session.subagent_records = [
        SubagentRunRecord(
            delegation_id="delegation-large-restore",
            parent_run_id="old-parent-run",
            status="abandoned",
            phase="recovered",
            task_label="大历史恢复",
            reason_code="process_restarted",
            cleanup_uncertain=True,
        )
    ]

    await app._restore_large_session(session)

    blocks = [block for block in app.model.transcript.blocks if isinstance(block, SubagentBlock)]
    assert len(blocks) == 1
    assert blocks[0].status == "abandoned"
    assert blocks[0].reason_code == "process_restarted"
    assert not app.model.status.subagent_counts


async def test_restore_failure_keeps_current_tui_usable(monkeypatch):
    """恢复失败显示诊断，同时允许当前会话继续接收输入。"""
    app, _, manager = _make_app()
    session = manager.current
    session.history = [Message(role="user", content=f"old-{i}") for i in range(1001)]

    async def fail_to_thread(fn, *args):
        raise OSError("snapshot unavailable")

    monkeypatch.setattr(asyncio, "to_thread", fail_to_thread)
    await app._restore_large_session(session)

    assert app.model.runtime.error_code == "restore_failed"
    assert app.model.running is False
    assert "恢复会话失败" in "\n".join(app.model.transcript.all_lines(120))

    monkeypatch.undo()
    app._submit("继续输入")
    await _wait_for_conversation(app)
    assert manager.current.run_texts == ["继续输入"]



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


def test_name_command_sets_and_displays_current_title():
    app, backend, manager = _make_app()

    backend.submit("/name   重构\n auth 模块  ")
    assert manager.current.title == "重构 auth 模块"
    assert "已设置会话标题: 重构 auth 模块" in _rendered_text(app, backend)

    backend.submit("/name")
    text = _rendered_text(app, backend)
    assert "当前会话标题: 重构 auth 模块" in text
    assert "/name <title>" in text

    backend.submit("/sessions list")
    assert "重构 auth 模块" in _rendered_text(app, backend)
    backend.submit("/tree")
    assert "重构 auth 模块" in _rendered_text(app, backend)


def test_name_command_rejects_blank_without_starting_conversation():
    app, backend, manager = _make_app()
    before = list(manager.current.run_texts)

    backend.submit("/name   ")

    assert manager.current.title == ""
    assert manager.current.run_texts == before
    assert "标题不能为空" in _rendered_text(app, backend)


def test_name_command_reports_storage_failure_without_running_conversation():
    app, backend, manager = _make_app()
    before = list(manager.current.run_texts)

    def fail_rename(session_id, title):
        raise OSError("磁盘不可用")

    manager.rename = fail_rename
    backend.submit("/name 新标题")

    assert manager.current.run_texts == before
    assert "设置会话标题失败: 磁盘不可用" in _rendered_text(app, backend)


def test_name_command_reports_missing_current_session():
    app, backend, manager = _make_app()
    manager.current = None

    backend.submit("/name 新标题")

    assert "无法设置会话标题: 当前没有会话" in _rendered_text(app, backend)



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


def test_sessions_search_matches_title_or_id_without_running_model():
    """/sessions search 只查询列表,不把搜索文本提交给当前会话。"""
    app, backend, manager = _make_app()
    manager.current.title = "Auth migration"
    before = list(manager.current.run_texts)

    backend.submit("/sessions search auth")

    text = _rendered_text(app, backend)
    assert "搜索结果 (1)" in text
    assert "Auth migration" in text
    assert manager.current.session_id in text
    assert manager.current.run_texts == before


def test_sessions_filter_supports_quoted_combined_conditions():
    """/sessions filter 支持带空格的标题和多个条件组合。"""
    app, backend, manager = _make_app()
    manager.current.title = "Auth module"
    manager.current.model = "DeepSeek-V4"
    manager.current.status = "completed"
    matching_id = manager.current.session_id
    other = manager.create()
    other.title = "Auth unrelated"
    other.model = "Qwen"
    other.status = "idle"
    before = list(manager.current.run_texts)

    backend.submit(
        '/sessions filter title="Auth module" model=deepseek status=completed'
    )

    text = _rendered_text(app, backend)
    assert "筛选结果 (1)" in text
    assert "Auth module" in text
    assert "DeepSeek-V4" in text
    assert "completed" in text.replace(" ", "")
    assert matching_id in text
    assert other.session_id not in text
    assert manager.current.run_texts == before


def test_sessions_query_reports_invalid_and_empty_results_inline():
    """查询错误和空态就地反馈,不切换会话或发起模型请求。"""
    app, backend, manager = _make_app()
    current = manager.current
    before = list(current.run_texts)

    backend.submit("/sessions filter status=unknown")
    assert "筛选失败" in _rendered_text(app, backend)
    assert manager.current is current
    assert manager.current.run_texts == before

    backend.submit("/sessions search no-such-session")
    assert "搜索结果: 无匹配会话" in _rendered_text(app, backend)
    assert manager.current is current
    assert manager.current.run_texts == before


def test_sessions_recovery_command_shows_actionable_report_without_switching():
    app, backend, manager = _make_app()
    current = manager.current
    report = SessionRecoveryReport(
        "fake-1",
        "degraded",
        (
            RecoveryDiagnostic(
                "malformed_record",
                "发现损坏记录",
                "1 条记录未恢复",
                "请先备份文件后继续",
            ),
        ),
        valid_message_count=2,
        skipped_record_count=1,
    )
    manager.recovery_report = lambda session_id: report

    backend.submit("/sessions recovery fake-1")

    text = _rendered_text(app, backend)
    assert "degraded" in text
    assert "malformed_record" in text
    assert "请先备份文件后继续" in text
    assert manager.current is current
    assert manager.current.run_texts == []


def test_sessions_switch_recovery_error_keeps_current_and_shows_code():
    report = SessionRecoveryReport(
        "bad",
        "unavailable",
        (
            RecoveryDiagnostic(
                "incompatible_version",
                "会话版本不兼容",
                "无法安全解释会话记录",
                "请升级客户端后迁移",
            ),
        ),
    )

    class RecoveryManager(FakeManager):
        def switch(self, session_id):
            raise SessionRecoveryError(report)

    backend = StubBackend()
    manager = RecoveryManager()
    app = TuiApp(manager, backend)
    backend.on_submit(app._submit)
    current = manager.current

    backend.submit("/sessions bad")

    text = _rendered_text(app, backend)
    assert "incompatible_version" in text
    assert "请升级客户端后迁移" in text
    assert manager.current is current


def test_degraded_session_hydration_reports_warning_and_keeps_input_available():
    app, _, manager = _make_app()
    manager.current.recovery_report = SessionRecoveryReport(
        manager.current.session_id,
        "degraded",
        (
            RecoveryDiagnostic(
                "compaction_cut_missing",
                "压缩切点消息不存在",
                "恢复回退为有效历史",
                "必要时重新压缩",
            ),
        ),
        valid_message_count=1,
        skipped_record_count=0,
    )

    app._hydrate_current_session()

    text = "\n".join(app.model.transcript.all_lines(120))
    assert "degraded" in text
    assert "compaction_cut_missing" in text


def test_sessions_archive_and_unarchive_keep_commands_read_only_to_model():
    """归档/恢复只改变会话元数据,不将命令交给模型。"""
    app, backend, manager = _make_app()
    first = manager.current
    before = list(first.run_texts)

    backend.submit(f"/sessions archive {first.session_id}")
    assert "已归档" in _rendered_text(app, backend)
    assert manager.current is first
    assert manager.current.run_texts == before

    backend.submit("/sessions archived")
    assert first.session_id in _rendered_text(app, backend)

    backend.submit(f"/sessions unarchive {first.session_id}")
    assert "已取消归档" in _rendered_text(app, backend)
    backend.submit("/sessions list")
    assert first.session_id in _rendered_text(app, backend)


def test_sessions_delete_requires_confirmation_and_supports_batch():
    """删除必须带 confirm,确认后批量删除非当前会话。"""
    app, backend, manager = _make_app()
    first = manager.current
    second = manager.create()
    third = manager.create()
    before = list(manager.current.run_texts)

    backend.submit(f"/sessions delete {first.session_id} {second.session_id}")
    assert "confirm" in _rendered_text(app, backend)
    assert len(manager.sessions) == 3

    backend.submit(
        f"/sessions delete {first.session_id} {second.session_id} confirm"
    )
    text = _rendered_text(app, backend)
    assert "已删除" in text
    assert first.session_id not in [item.session_id for item in manager.sessions]
    assert second.session_id not in [item.session_id for item in manager.sessions]
    assert manager.current is third
    assert manager.current.run_texts == before



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
