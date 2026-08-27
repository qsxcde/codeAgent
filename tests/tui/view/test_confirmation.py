"""TUI view confirmation behavior tests."""

from tests.tui.view.fixtures import *  # noqa: F401,F403


def test_confirmation_event_shows_bar():
    """确认请求事件 → 确认条渲染(工具/摘要/原因可见),后端激活。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    manager = app._manager
    manager.current._emit(_confirm_event())
    assert backend.confirmation_lines[-1], "确认条未显示"
    plain = "".join(s.text for line in backend.confirmation_lines[-1] for s in line)
    assert "需要确认" in plain
    assert "git push origin main" in plain
    assert "推送远程分支" in plain
    assert app._pending_confirmation is not None



def test_confirmation_yes_forwards_approval():
    """y 响应 → 会话 respond_approval(request_id, True),确认条收起。"""
    app, backend, manager = _make_app()
    manager.current._emit(_confirm_event())
    backend.confirmation_response(True)
    assert manager.current.approvals == [("cf-r1", True)]
    assert backend.confirmation_lines[-1] == []
    assert app._pending_confirmation is None



def test_confirmation_no_forwards_rejection():
    """n 响应 → 会话 respond_approval(request_id, False),确认条收起。"""
    app, backend, manager = _make_app()
    manager.current._emit(_confirm_event())
    backend.confirmation_response(False)
    assert manager.current.approvals == [("cf-r1", False)]



def test_esc_while_confirmation_aborts_run():
    """确认激活时 Esc → 中断当前运行(拒绝并中止语义;RUN_CANCELLED 后条收起)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    manager.current._emit(_confirm_event())
    backend.interrupt()
    assert manager.current.aborted is True
    manager.current._emit(AgentEvent(EventType.RUN_CANCELLED))
    assert app._pending_confirmation is None
    assert backend.confirmation_lines[-1] == []



def test_terminal_event_clears_confirmation_bar():
    """终态事件(TURN_END)→ 确认条收起(不再悬挂)。"""
    app, backend, manager = _make_app()
    manager.current._emit(_confirm_event())
    manager.current._emit(AgentEvent(EventType.TURN_END))
    assert app._pending_confirmation is None
    assert backend.confirmation_lines[-1] == []



def test_rejected_tool_result_marks_block():
    """拒绝的 TOOL_RESULT(rejected 元数据)→ 工具块进入拒绝态(图标 ✗)。"""
    app, _, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    app.model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "bash", "args": {"command": "git push"}, "id": "c1"}],
        )
    )
    app.model.apply(
        AgentEvent(
            EventType.TOOL_RESULT,
            payload="[工具执行被拒绝] 用户拒绝执行: 推送远程分支",
            metadata={"tool_call_id": "c1", "error": True, "rejected": True},
        )
    )
    block = next(b for b in app.model.transcript.blocks if isinstance(b, ToolCallBlock))
    assert block.rejected is True and block.status == "error"
    header = block.render(60)[0]
    assert header[2].text == "✗"
    assert "Rejected bash" in "".join(s.text for s in header)



def test_start_registers_confirmation_handler():
    """start() 注册确认响应回调(端口接线)。"""
    backend = StubBackend()
    app = TuiApp(FakeManager(), backend)
    app.start()
    assert backend.confirmation_response is not None
    backend.confirmation_response(True)  # 无 pending 时安全忽略

