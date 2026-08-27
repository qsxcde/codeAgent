"""TUI view commands behavior tests."""

from tests.tui.view.fixtures import *  # noqa: F401,F403


def test_retry_command_requires_safe_failure_and_continue_starts_new_prompt():
    app, backend, manager = _make_app()
    manager.current.last_failure = {
        "retryable": False,
        "cleanup_uncertain": True,
        "side_effect_state": "uncertain",
        "prompt": "old tool call",
    }
    backend.submit("/retry")
    assert "不可安全重试" in "\n".join(app.model.transcript.all_lines(120))
    backend.submit("/continue new plan")
    assert manager.current.run_texts == ["new plan"]



def test_quit_command_dispatches_and_exits():
    """/quit 命令 → 等同 Ctrl+C 退出(空闲态打印完整文档)。"""
    app, backend, manager = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))
    backend.on_submit(app._submit)
    backend.submit("/quit")
    assert backend.exited is not None
    doc = "\n".join(backend.exited)
    assert "hi" in doc
    assert "回复" in doc



def test_quit_command_running_is_ignored():
    """/quit 命令运行中 → 输入框提交被忽略(与其他命令一致,不退出)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    backend.on_submit(app._submit)
    backend.submit("/quit")
    assert backend.exited is None
    assert manager.current.aborted is False



def test_submit_command_help_renders_without_run():
    """/help → 渲染命令帮助,不发起对话。"""
    app, backend, manager = _make_app()
    manager.current.run_called = False  # 记录:命令不应触发 run
    backend.submit("/help")
    # 无界高度渲染全文(命令表变长后视口会裁剪行首,不影响命令语义)。
    text = "\n".join(app.model.transcript.all_lines(240))
    assert "/fork" in text and "/compact" in text
    assert "/skills" in text



def test_submit_unknown_command_shows_error():
    """未知命令 → 可操作提示,不发送不执行(NFR-U7)。"""
    app, backend, _ = _make_app()
    backend.submit("/foobar")
    text = _rendered_text(app, backend)
    assert "未知命令: /foobar" in text
    assert "会话列表" not in text



def test_task_mode_command_updates_sticky_mode():
    app, backend, _ = _make_app()
    backend.submit("/mode plan")

    assert app.model.status.mode == "plan"
    assert "已切换到 plan 模式" in "\n".join(app.model.transcript.all_lines(120))



async def test_submit_double_slash_sends_literal():
    """// 转义 → 按字面量发起对话(去掉一个 /)。"""
    app, backend, manager = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        backend.submit("//hi")
        await _wait_for_conversation(app)

    await (_run())
    text = _rendered_text(app, backend)
    assert "/hi" in text  # SESSION_STARTED payload 为转义后的字面量



def test_clear_command_resets_transcript():
    """/clear → 清空聊天区。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="旧内容"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))  # 回空闲,命令才可提交
    assert app.model.transcript.blocks
    backend.submit("/clear")
    assert app.model.transcript.blocks == []
    assert app.model.transcript.follow is True



def test_tools_command_lists_tool_names():
    """/tools → 列出可用工具。"""
    app, backend, manager = _make_app()
    manager.tools = [type("T", (), {"name": "bash"})(), type("T", (), {"name": "read"})()]
    backend.submit("/tools")
    text = _rendered_text(app, backend)
    assert "bash" in text and "read" in text



def test_submit_after_confirm_executes_command():
    """(回归:D1)确认填入后直接提交,命令被执行而非再次确认。"""
    app, backend, _ = _make_app()
    backend.input_changed("/tools")
    backend.suggestion_confirm()
    backend.input_changed("/tools")  # 异步变更通知(被抑制)
    backend.submit("/tools")
    assert "可用工具" in _rendered_text(app, backend)



def test_bare_slash_shows_all_commands():
    """(回归:D2)单独输入 / 展示全量命令建议(注册表原序)。

    回归(cost-transparency):候选列表必须容纳注册表全量——按 fuzzy_rank
    排名截断会把排后命令(如 /quit /fork /compact /skills /mcp)永久隐藏;
    渲染层用固定窗口裁剪视口,但候选本身不截断(浮层可滚动到达全部)。
    """
    from codeagent.app.tui.commands import default_registry

    app, backend, _ = _make_app()
    backend.input_changed("/")
    # 候选列表 = 注册表全量(原序),不按排名截断。
    assert app._suggestions == list(default_registry())

