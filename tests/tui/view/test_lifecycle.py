"""TUI view lifecycle behavior tests."""

from tests.tui.view.fixtures import *  # noqa: F401,F403

from codeagent.app.tasks.supervisor import TaskSupervisor
from codeagent.app.tui.presentation.blocks import ErrorBlock


def test_fake_backend_regression_contract_covers_top_level_interactions():
    """FakeBackend 合同固定输入、命令、确认、切换、滚动、恢复、取消和退出边界。

    细节行为由本文件下方的专项测试覆盖；这个场景把拆分协调器时必须保持的
    顶层接线串起来，避免只迁移单个方法后遗漏后端端口。
    """
    app, backend, manager = _make_app()

    backend.submit("/help")
    assert "可用命令" in "\n".join(app.model.transcript.all_lines(120))

    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="prompt"))
    app.model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "bash", "args": {"command": "echo ok"}, "id": "c1"}],
        )
    )
    manager.current._emit(_confirm_event())
    assert backend.confirmation_lines[-1]
    backend.confirmation_response(True)

    app.model.transcript.render(60, 10)
    backend.scroll(3)
    assert app.model.transcript.follow is False

    manager.create()
    app._hydrate_current_session()
    app.model.apply(AgentEvent(EventType.RUN_CANCELLED))
    assert app.model.running is False

    backend.quit()
    assert backend.exited is not None



async def test_submit_starts_run_and_renders():
    """提交触发会话运行,事件驱动渲染(对应 spec「对话输入与回复渲染」)。"""
    app, backend, _ = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        backend.submit("你好")
        await _wait_for_conversation(app)

    await (_run())
    rendered_plain = ["".join(rich_to_plain(lines)) for lines in backend.renders]
    assert any("你好" in text for text in rendered_plain)
    assert "ok" in rendered_plain[-1]
    assert app.model.running is False
    # 状态栏以富样式行传递(design D5)。
    assert backend.statuses and all(isinstance(s, list) for s in backend.statuses)
    assert "ready" not in "".join(s.text for s in backend.statuses[-1])



async def test_submit_echoes_user_before_async_conversation_starts():
    app, backend, _ = _make_app()

    async def _run() -> None:
        backend.submit("即时问题")
        assert "› 即时问题" in "\n".join(app.model.transcript.all_lines(120))
        await _wait_for_conversation(app)

    await (_run())


async def test_submit_renders_preparing_frame_before_session_run():
    """普通提交的首帧必须先于真实 session.run。"""
    app, backend, manager = _make_app()
    run_observations: list[tuple[str, int]] = []
    original_run = manager.current.run

    def observe_run(text: str, **kwargs):
        run_observations.append((text, len(backend.renders)))
        return original_run(text)

    manager.current.run = observe_run
    backend.submit("首帧反馈")

    try:
        assert backend.renders
        first_frame = "\n".join(rich_to_plain(backend.renders[0]))
        first_status = "".join(span.text for span in backend.statuses[0])
        assert "首帧反馈" in first_frame
        assert "准备任务" in first_status
        assert run_observations == []
    finally:
        await _wait_for_conversation(app)

    assert run_observations
    assert run_observations[0][0] == "首帧反馈"
    assert run_observations[0][1] >= 1


async def test_submit_failure_before_session_start_clears_pending_marker(monkeypatch):
    """真实会话尚未开始就失败时,后续提交不能继承旧的去重标记。"""
    app, backend, _ = _make_app()

    async def fail_before_session_start(*args, **kwargs):
        raise RuntimeError("model initialization unavailable")

    monkeypatch.setattr(TaskSupervisor, "run", fail_before_session_start)
    backend.submit("初始化失败")
    await _wait_for_conversation(app)

    assert app.model.running is False
    assert app.model._pending_user_prompts == []
    assert "任务执行失败，请查看日志。" in "\n".join(app.model.transcript.all_lines(120))


def test_submit_task_creation_failure_clears_preparing_state(monkeypatch):
    """任务监督器创建失败时,提交不会留下不可取消的准备态。"""
    app, backend, _ = _make_app()

    def fail_to_create(*args, **kwargs):
        raise RuntimeError("task supervisor unavailable")

    monkeypatch.setattr("codeagent.app.tui.session.conversation.TaskSupervisor", fail_to_create)
    backend.submit("创建失败")

    assert app.model.running is False
    assert app.model.activity_visible is False
    assert app.model._pending_user_prompts == []
    assert "任务启动失败，请查看日志。" in "\n".join(app.model.transcript.all_lines(120))


async def test_cancel_before_session_start_clears_preparing_state(monkeypatch):
    """真实会话尚未发出开始事件就取消时,准备态必须回到空闲。"""
    app, backend, manager = _make_app()
    started = asyncio.Event()
    hold = asyncio.Event()

    async def skip_baseline(self, mode):
        return None

    async def blocked_run(text: str, **kwargs):
        started.set()
        await hold.wait()

    monkeypatch.setattr(TaskSupervisor, "_capture_baseline", skip_baseline)
    manager.current.run = blocked_run
    backend.submit("取消准备")
    await started.wait()

    backend.interrupt()
    await _wait_for_conversation(app)

    assert manager.current.aborted is True
    assert app.model.running is False
    assert app.model.activity_visible is False
    assert app.model._pending_user_prompts == []


async def test_unexpected_task_failure_is_rendered_instead_of_becoming_orphaned(
    monkeypatch,
):
    app, backend, _ = _make_app()

    async def fail(*args, **kwargs):
        raise RuntimeError("verification service unavailable")

    monkeypatch.setattr(TaskSupervisor, "run", fail)
    backend.submit("触发失败")
    await _wait_for_conversation(app)

    assert any(isinstance(block, ErrorBlock) for block in app.model.transcript.blocks)
    rendered = "\n".join(app.model.transcript.all_lines(120))
    assert "任务执行失败，请查看日志。" in rendered
    assert "verification service unavailable" not in rendered
    assert app.model.running is False



def test_submit_during_busy_state_preserves_draft_and_explains_next_action():
    app, backend, manager = _make_app()
    app.model.running = True

    backend.submit("稍后发送")

    assert manager.current.run_texts == []
    assert backend.input_texts[-1] == "稍后发送"
    assert "等待" in _rendered_text(app, backend)



async def test_shutdown_is_idempotent_and_emits_complete_document():
    app, backend, _ = _make_app()
    app.model.append_info("退出前保留")

    async def _run() -> None:
        await app.shutdown()
        await app.shutdown()

    await (_run())

    assert backend.exited is not None
    assert any("退出前保留" in line for line in backend.exited)



async def test_shutdown_ignores_late_events_after_unsubscribe():
    app, backend, manager = _make_app()
    app.model.append_info("退出前状态")

    async def _run() -> None:
        await app.shutdown()
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="晚到"))

    await (_run())

    assert backend.exited is not None
    assert not any("晚到" in line for line in app.model.transcript.all_lines(80))



def test_interrupt_running_aborts():
    """运行中 Esc → abort 当前会话(对应 spec「运行中打断」)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    backend.interrupt()
    assert manager.current.aborted is True


def test_interrupt_running_schedules_cancel_feedback_without_waiting_for_terminal_event():
    """Esc 触发 abort 后立即安排一帧,不等待会话终态事件才刷新 UI。"""
    app, backend, manager = _make_app()
    app.model.running = True
    before = len(backend.renders)

    backend.interrupt()

    assert manager.current.aborted is True
    assert len(backend.renders) == before + 1



def test_interrupt_idle_prompts_quit_hint():
    """空闲 Esc → 提示「按 Ctrl+C 退出」,不再直接退出(收尾补丁:退出键位拆分)。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))  # 结束本轮 → 空闲
    backend.interrupt()
    assert backend.exited is None  # 不退出
    text = _rendered_text(app, backend)
    assert "Ctrl+C" in text



def test_quit_idle_exits_with_doc():
    """空闲 Ctrl+C → 退出并打印完整文档(对应 spec「退出完整文档」)。"""
    app, backend, manager = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="hi"))
    app.model.apply(AgentEvent(EventType.TEXT_DELTA, payload="回复"))
    app.model.apply(AgentEvent(EventType.TURN_END))
    backend.quit()
    assert backend.exited is not None
    doc = "\n".join(backend.exited)
    assert "hi" in doc
    assert "回复" in doc



def test_quit_running_aborts_then_exits():
    """运行中 Ctrl+C → 先中止当前轮(abort),再退出(未完成轮次不落盘)。"""
    app, backend, manager = _make_app()
    app.model.running = True
    backend.quit()
    assert manager.current.aborted is True
    assert backend.exited is not None



def test_run_cancelled_event_returns_idle():
    """RUN_CANCELLED 事件 → 运行态回空闲(对应 spec「运行中打断」)。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    assert app.model.running is True
    app.model.apply(AgentEvent(EventType.RUN_CANCELLED))
    assert app.model.running is False
    assert app.model.activity_visible is False



async def test_render_coalescing():
    """N 个增量事件合并成一次渲染(对应 spec「帧率达标」;design D4)。"""
    app, backend, manager = _make_app()

    async def _run() -> None:
        backend.resize()
        await asyncio.sleep(0)
        before = len(backend.renders)
        # 同一循环迭代内连发多个增量
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="a"))
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="b"))
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="c"))
        for _ in range(10):
            if len(backend.renders) - before >= 1:
                break
            await asyncio.sleep(0)
        assert len(backend.renders) - before == 1

    await (_run())



@pytest.mark.slow
async def test_render_scheduler_delays_frames_inside_target_interval():
    app, backend, manager = _make_app()

    async def scenario() -> None:
        backend.resize()
        await asyncio.sleep(0)
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="a"))
        await asyncio.sleep(0)
        before = len(backend.renders)
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="b"))
        await asyncio.sleep(0)
        assert len(backend.renders) == before
        await asyncio.sleep(0.04)
        assert len(backend.renders) == before + 1

    await (scenario())



async def test_activity_timer_runs_only_while_visible():
    """活动提示有独立 UI 定时器，正文到达后立即停止。"""
    app, _, manager = _make_app()

    async def _run() -> None:
        manager.current._emit(AgentEvent(EventType.SESSION_STARTED, payload="x"))
        await asyncio.sleep(0)
        task = app._activity_task
        assert task is not None and not task.done()
        manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="reply"))
        await asyncio.sleep(0)
        assert app._activity_task is None

    await (_run())



def test_click_toggles_tool_expand():
    """点击工具行 → 切换折叠(spec「工具调用点击展开」;design D4)。"""
    app, backend, _ = _make_app()
    app.model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    app.model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "read", "args": {"file_path": "a.py"}, "id": "c1"}],
        )
    )
    app.model.transcript.render(60, 10)  # 填充行→块映射
    tool = next(b for b in app.model.transcript.blocks if isinstance(b, ToolCallBlock))
    assert tool.expanded is False
    row = next(i for i in range(10) if app.model.transcript.block_at(i) is tool)
    backend.click(row)
    assert tool.expanded is True
    backend.click(row)
    assert tool.expanded is False



def test_wheel_scroll_up_unfollows_and_new_output_does_not_jump():
    """滚轮上滚 → 解除跟随;新输出不强制跳回底部(spec「上滚浏览历史」)。"""
    app, backend, manager = _make_app()
    _fill_transcript(app)
    assert app.model.transcript.follow is True
    backend.scroll(3)  # 滚轮一格(上滚)
    assert app.model.transcript.follow is False
    first_line = app.model.transcript.render(60, 10)[0][0].text
    # 上滚后新正文到达:不跳回底部,视口内容不变
    manager.current._emit(AgentEvent(EventType.TEXT_DELTA, payload="new "))
    manager.current._emit(AgentEvent(EventType.TURN_END))
    assert app.model.transcript.follow is False
    assert app.model.transcript.render(60, 10)[0][0].text == first_line



def test_scroll_back_to_bottom_restores_follow():
    """滚回底部 → 恢复跟随(spec「回到底部恢复跟随」)。"""
    app, backend, _ = _make_app()
    _fill_transcript(app)
    backend.scroll(3)
    assert app.model.transcript.follow is False
    backend.scroll(-1000)  # 持续下滚越过底部
    app.model.transcript.render(60, 10)
    assert app.model.transcript.follow is True



def test_keyboard_page_up_down_dispatches_scroll():
    """PageUp/PageDown → 一页行数增量,上翻解除跟随、下翻回底恢复(spec「键盘滚动」)。"""
    app, backend, _ = _make_app()
    _fill_transcript(app)
    backend.scroll(9)  # PageUp 一页(视口高 10 - 1):解除跟随
    assert app.model.transcript.follow is False
    backend.scroll(9)  # PageUp 再一页:位置 20 → 2
    backend.scroll(-9)  # PageDown 一页:2 → 11,未到底,仍不跟随
    assert app.model.transcript.follow is False
    backend.scroll(-1000)  # PageDown 越过底部
    app.model.transcript.render(60, 10)
    assert app.model.transcript.follow is True



def test_start_registers_scroll_handler():
    """start() 注册 on_scroll 回调(端口接线;design T-47)。"""
    backend = StubBackend()
    app = TuiApp(FakeManager(), backend)
    app.start()  # StubBackend.run 为 no-op,只测注册
    assert backend.scroll is not None
    assert backend.scroll(5) is None  # 处理器可调用且不抛错



def test_confirm_suppresses_async_repopulate():
    """(回归:D1)确认填入后,set_input_text 引发的异步变更通知不重弹浮层。

    早期缺陷:confirm 同步清理浮层,但异步 Changed 事件重算建议使浮层复活,
    Enter 永远被消费为确认,命令无法提交。正确行为:该次通知被抑制,
    浮层保持收起;后续真实编辑恢复正常建议计算。
    """
    app, backend, _ = _make_app()
    backend.input_changed("/tools")
    assert app._suggestions == ["tools"]
    backend.suggestion_confirm()
    assert backend.input_texts[-1] == "/tools"
    # 模拟 textual 异步投递的 Changed 通知(内容 = 填入后的文本)。
    backend.input_changed("/tools")
    assert app._suggestions == []
    assert backend.suggestion_lines[-1] == []
    # 标志只消费一次:继续编辑恢复正常建议计算。
    backend.input_changed("/to")
    assert app._suggestions == ["tools"]



def test_selector_empty_arg_shows_all_candidates():
    """(回归:D4)/model 等选择器空参(仅尾随空格)展示全量候选。"""
    app, backend, _ = _make_app()
    app._candidates = {
        "provider": ["deepseek", "openai"],
        "model": {"deepseek": ["deepseek-v4-pro", "deepseek-v4-flash"]},
        "effort": ["low", "medium", "high"],
    }
    app._provider = "deepseek"
    backend.input_changed("/model ")
    assert app._suggestions == ["deepseek-v4-pro", "deepseek-v4-flash"]
    backend.input_changed("/provider ")
    assert app._suggestions == ["deepseek", "openai"]
    backend.input_changed("/effort ")
    assert app._suggestions == ["low", "medium", "high"]
    # 无空格仍是命令名补全,不进选择器。
    backend.input_changed("/model")
    assert app._suggestions == ["model"]
