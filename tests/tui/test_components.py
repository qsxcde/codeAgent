"""tests/tui/test_components.py:组件树 + TuiModel 事件映射 + 样式标签断言。

对应 spec「消息样式区分」(标签可离线断言)、「用户消息背景块」「思考活动反馈」
「工具调用过程可见」「工具调用点击展开」「状态栏会话元信息」「alt 屏渲染与滚动」。
"""

import unicodedata

from codeagent.app.tui.components import (
    AssistantBlock,
    ActivityBlock,
    CancelledBlock,
    ErrorBlock,
    FooterInfo,
    Span,
    StatusBar,
    ToolCallBlock,
    Transcript,
    TuiModel,
    UserBlock,
    rich_to_plain,
)
from codeagent.app.tui.theme import (
    ACCENT,
    ACTIVITY,
    ASSISTANT_PROMPT,
    DIM,
    ERROR,
    DIFF_ADD,
    DIFF_REMOVE,
    SUCCESS,
    STATUS_MODEL,
    STATUS_PATH,
    TEXT,
    TOOL_OUTPUT,
    USER_BG,
    USER_PROMPT,
    WARNING,
)
from codeagent.core.events import AgentEvent, EventType
from codeagent.core.messages import Message, ToolCall


class _FakeClock:
    """假时钟:按调用顺序返回预设值(测思考耗时显示,design D3)。"""

    def __init__(self, *values: float) -> None:
        self._values = list(values)

    def __call__(self) -> float:
        return self._values.pop(0)


def _cells(text: str) -> int:
    """测试用:终端 cell 宽度(CJK 等宽/全角按 2 格,与组件层一致)。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def test_user_block_is_full_width_background():
    """用户消息每行均为连续的深灰背景，并带低对比提示符。"""
    lines = UserBlock("hi").render(10)
    assert lines[0][0].fg == USER_PROMPT and lines[0][0].text == "› "
    assert lines[0][1].fg == TEXT and lines[0][1].text == "hi"
    assert all(span.bg == USER_BG for span in lines[0])
    assert len("".join(span.text for span in lines[0])) == 10


def test_user_block_padding_by_cell_width():
    """中文用户消息背景按 cell 宽度补齐(回归:len() 按 1 计导致背景缺一段)。"""
    lines = UserBlock("你好").render(8)  # "› " 2 cell + "你好" 4 cell → 补齐 2 空格
    assert lines[0][2].text == "  " and lines[0][2].bg == USER_BG
    assert all(span.bg == USER_BG for span in lines[0])
    assert _cells("".join(s.text for s in lines[0])) == 8  # 背景铺满整行


def test_assistant_hides_thinking_and_renders_bullet_body():
    """推理仍累积，但聊天区只显示圆点前缀的正文。"""
    block = AssistantBlock(clock=_FakeClock(0.0, 1.0))
    block.append_thinking("让我想想")
    block.append_text("正文")
    lines = block.render(60)
    assert lines[0][0].fg == ASSISTANT_PROMPT and lines[0][0].text == "• "
    assert any(span.fg == TEXT and span.text == "正文" for line in lines for span in line)
    assert "让我想想" not in "".join(span.text for line in lines for span in line)


def test_assistant_without_body_renders_nothing():
    block = AssistantBlock(clock=_FakeClock(2.0, 5.0))
    block.append_thinking("a")
    assert block.render(60) == []
    block.append_text("b")
    assert rich_to_plain(block.render(60)) == ["• b"]


def test_tui_model_hydrates_persisted_history():
    """会话切换后,持久化消息应按原顺序重建用户/助手/工具块。"""
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="旧会话输入"))
    model.apply(AgentEvent(EventType.TEXT_DELTA, payload="旧会话回复"))

    call = ToolCall(id="call-1", name="read", args={"file_path": "a.py"})
    model.hydrate_history(
        [
            Message(role="user", content="恢复的问题"),
            Message(role="assistant", content="恢复的回答"),
            Message(role="assistant", tool_calls=[call]),
            Message(role="tool", content="文件内容", tool_call_id="call-1"),
        ]
    )

    plain = "\n".join(rich_to_plain(model.transcript.all_rich(80)))
    assert "› 恢复的问题" in plain
    assert "• 恢复的回答" in plain
    assert "Read a.py" in plain
    tool = next(block for block in model.transcript.blocks if isinstance(block, ToolCallBlock))
    assert tool.status == "done"
    assert model.running is False
    assert model.activity_visible is False


def test_tui_hides_manual_skill_markdown_but_keeps_loaded_label():
    """手动加载 Skill 时只显示简短标签，完整 Markdown 不进入 TUI transcript。"""
    invocation = (
        "[用户手动加载技能: fmt]\n"
        '<skill name="fmt" location="/skills/fmt/SKILL.md">\n'
        "SECRET-SKILL-MARKDOWN\n"
        "</skill>"
    )
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload=invocation))
    live = "\n".join(rich_to_plain(model.transcript.all_rich(120)))

    assert "已加载技能: fmt" in live
    assert "SECRET-SKILL-MARKDOWN" not in live
    assert "/skills/fmt/SKILL.md" not in live

    model.hydrate_history([Message(role="user", content=invocation)])
    restored = "\n".join(rich_to_plain(model.transcript.all_rich(120)))
    assert "已加载技能: fmt" in restored
    assert "SECRET-SKILL-MARKDOWN" not in restored


def test_assistant_wraps_cjk_by_cell_width():
    """中文字符按 2 cell 计宽:换行位置不超视口(回归:len() 按 1 计导致中文行
    实际超宽被终端裁掉)。"""
    block = AssistantBlock()
    block.append_text("一二三四五六七八九十")  # 10 字符 = 20 cell
    lines = block.render(12)  # inner = 10 cell → 每行最多 5 个中文字符
    texts = ["".join(s.text for s in line) for line in lines]
    assert texts == ["• 一二三四五", "  六七八九十"]
    assert all(_cells(text) <= 12 for text in texts)  # 每行不超视口


def test_activity_block_has_low_frequency_frames():
    assert rich_to_plain(ActivityBlock(0).render(60)) == ["• 思考中 ·"]
    assert rich_to_plain(ActivityBlock(2).render(60)) == ["• 思考中 ···"]
    assert ActivityBlock(1).render(60)[0][1].fg == ACTIVITY


def test_tool_call_folded_by_default():
    """工具默认折叠:折叠符 ▶ + 状态图标 + accent 名 + 参数摘要(design D4)。"""
    block = ToolCallBlock("read", {"file_path": "a.py"})
    block.set_result("file content")
    lines = block.render(60)
    assert len(lines) == 1  # 只 header,结果隐藏
    header = lines[0]
    assert header[0].text == "▶" and header[0].fg == DIM
    assert header[2].text == "✓" and header[2].fg == SUCCESS
    assert any(s.fg == ACCENT and s.text == "Read a.py" for s in header)
    assert any("a.py" in s.text for s in header)
    # 参数摘要,非 JSON
    assert "{" not in "".join(s.text for s in header)


def test_tool_call_expand_shows_result():
    """点击展开后折叠符变 ▼,结果行出现,样式 tool_output(spec「工具调用点击展开」)。"""
    block = ToolCallBlock("read", {})
    block.set_result("file content")
    block.toggle_expand()
    lines = block.render(60)
    assert len(lines) == 2
    assert lines[0][0].text == "▼"
    assert lines[1][0].fg == TOOL_OUTPUT and "file content" in lines[1][0].text


def test_tool_call_error_icon():
    block = ToolCallBlock("bash", {"command": "npm run build"})
    block.set_result("退出码 1", error=True)
    header = block.render(60)[0]
    assert header[2].fg == ERROR and header[2].text == "✗"


def test_tool_result_error_metadata_marks_error_status():
    """TOOL_RESULT 事件 metadata 带 error 时工具块进入失败态(回归:契约断裂)。

    早期缺陷:session 不透传错误标志,TUI 的 error 判定恒为 False,
    工具失败永远显示 ✓ 成功图标而非 ✗。
    """
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "bash", "args": {"command": "false"}, "id": "c1"}],
        )
    )
    tool = next(b for b in model.transcript.blocks if isinstance(b, ToolCallBlock))
    model.apply(
        AgentEvent(
            EventType.TOOL_RESULT,
            payload="[工具执行出错] 退出码 1",
            metadata={"tool_call_id": "c1", "error": True},
        )
    )
    assert tool.status == "error"
    header = tool.render(60)[0]
    assert header[2].text == "✗" and header[2].fg == ERROR
    assert "Failed bash" in "".join(s.text for s in header)


def test_tool_call_has_human_readable_pending_summary():
    block = ToolCallBlock("bash", {"command": "uv run pytest -q"})
    plain = "".join(s.text for s in block.render(60)[0])
    assert "Running command" in plain
    assert "{" not in plain and "uv run pytest -q" not in plain


def test_tool_call_result_summary():
    """结果摘要:bash 退出码/耗时、write 字节、edit 处数;解析失败回退首行(design D4)。"""
    bash = ToolCallBlock("bash", {})
    bash.set_result("退出码: 0(耗时 12.3s)\nstdout: ok")
    assert "exit 0 · 12.3s" in "".join(s.text for s in bash.render(60)[0])

    write = ToolCallBlock("write", {"file_path": "a.py", "content": "one\ntwo"})
    write.set_result("已写入 a.py(120 字节)")
    assert "Wrote a.py (+2)" in "".join(s.text for s in write.render(60)[0])

    edit = ToolCallBlock("edit", {"file_path": "a.py", "old_string": "old", "new_string": "new"})
    edit.set_result("已替换 2 处: a.py")
    assert "Edited a.py (+1 -1)" in "".join(s.text for s in edit.render(60)[0])

    other = ToolCallBlock("grep", {})
    other.set_result("第一行\n第二行")
    plain = "".join(s.text for s in other.render(60)[0])
    assert "Ran grep" in plain


def test_edit_tool_expand_shows_intent_diff_with_colored_rows():
    block = ToolCallBlock(
        "edit", {"file_path": "a.py", "old_string": "old", "new_string": "new"}
    )
    block.set_result("已替换 1 处: a.py")
    block.toggle_expand()
    lines = block.render(60)
    assert any(span.text == "- old" and span.bg == DIFF_REMOVE for line in lines for span in line)
    assert any(span.text == "+ new" and span.bg == DIFF_ADD for line in lines for span in line)


def test_error_and_cancelled_spans():
    assert ErrorBlock("boom").render(60)[0][0].fg == ERROR
    assert CancelledBlock().render(60)[0][0].fg == WARNING


def test_status_bar_renders_codex_session_metadata():
    """状态栏只显示模型、思考强度和工作目录，不显示状态点或快捷键。"""
    bar = StatusBar()
    bar.model = "gpt-5.6-terra"
    bar.effort = "high"
    bar.cwd = "/mnt/c/Windows/System32"
    line = bar.render(60)[0]
    plain = "".join(s.text for s in line)
    assert plain == "  gpt-5.6-terra high · /mnt/c/Windows/System32"
    assert line[1].fg == STATUS_MODEL
    assert line[-1].fg == STATUS_PATH
    assert "ready" not in plain and "Esc" not in plain and "●" not in plain


def test_status_bar_truncates_session_metadata():
    """窄终端截断右侧路径，模型信息仍保持在左侧。"""
    bar = StatusBar()
    bar.model = "gpt-5.6-terra"
    bar.effort = "high"
    bar.cwd = "/a/very/long/working/directory"
    line = bar.render(24)[0]
    plain = "".join(s.text for s in line)
    assert len(plain) == 24
    assert plain.startswith("  gpt-5.6-terra")
    assert plain.endswith("…")


def test_status_bar_truncates_cjk_metadata():
    """含中文的状态栏按 cell 宽度截断且不超宽(回归:len() 截断导致超限)。"""
    bar = StatusBar()
    bar.model = "深度思考模型"
    line = bar.render(10)[0]
    plain = "".join(s.text for s in line)
    assert plain.endswith("…")
    assert _cells(plain) <= 10


def test_status_bar_renders_context_usage_on_right():
    """状态栏右侧显示上下文占用、窗口上限与低占用进度条。"""
    from codeagent.app.tui.theme import ACCENT

    bar = StatusBar()
    bar.model = "deepseek-v4-flash"
    bar.effort = "high"
    bar.cwd = r"D:\project\codeAgent"
    bar.context_tokens = 12_400
    bar.context_window = 128_000

    line = bar.render(100)[0]
    plain = "".join(s.text for s in line)

    assert plain.endswith("上下文 12.4k / 128k · 9.7%")
    assert "▰" in plain and "▱" in plain
    assert any(span.fg == ACCENT for span in line)
    assert _cells(plain) <= 100


def test_status_bar_shows_context_window_before_first_usage():
    """尚未收到 provider usage 时显示窗口上限,不伪造当前占用。"""
    bar = StatusBar()
    bar.context_window = 128_000

    plain = "".join(s.text for s in bar.render(60)[0])

    assert plain.endswith("上下文 — / 128k")


def test_status_bar_shows_task_verification_progress():
    bar = StatusBar()
    bar.set_task_status("verifying", command="python -m pytest", attempt=1, max_attempts=2)

    plain = "".join(s.text for s in bar.render(100)[0])

    assert "验证中" in plain
    assert "第 1/2 次" in plain
    assert "python -m pytest" in plain


def test_truncate_cjk_by_cell_width():
    """_truncate 按 cell 宽度截断并预留省略号(回归:len() 截断后中文行仍超宽)。"""
    from codeagent.app.tui.components import _truncate

    assert _truncate("很" * 31, 60) == "很" * 29 + "…"
    assert _cells(_truncate("很" * 31, 60)) <= 60
    assert _truncate("hello world", 8) == "hello w…"


def test_transcript_follow_end():
    """跟底 / 上滚解跟随 / 回底恢复(spec「alt 屏渲染与滚动」)。"""
    transcript = Transcript()

    class _FakeBlock:
        def render(self, width):
            return [[Span(f"line{i}")] for i in range(30)]

    transcript.append(_FakeBlock())
    view = transcript.render(60, 10)
    assert len(view) == 10
    assert view[0][0].text == "line20"
    assert transcript.follow is True
    transcript.scroll(5)
    assert transcript.follow is False
    view = transcript.render(60, 10)
    assert view[0][0].text == "line15"
    transcript.scroll_to_bottom()
    assert transcript.follow is True


def test_block_at_maps_line_to_block():
    """视口行号 → 所属块(design D4;工具点击命中)。"""
    transcript = Transcript()
    user = UserBlock("hi")
    tool = ToolCallBlock("read", {})
    transcript.append(user)
    transcript.append(tool)
    transcript.render(60, 10)
    assert transcript.block_at(0) is user
    assert transcript.block_at(1) is None
    assert transcript.block_at(2) is tool
    assert transcript.block_at(99) is None


def test_block_at_maps_after_scroll():
    """上滚后 block_at 仍命中视口行对应的块(回归:此前映射不随滚动偏移)。

    早期缺陷:行→块映射从内容第 0 行开始、不随 start 偏移,上滚后点击
    工具块会命中错误的块(refine-tui-layout 遗留)。
    """
    transcript = Transcript()
    blocks = [UserBlock(f"m{i}") for i in range(20)]
    for b in blocks:
        transcript.append(b)
    transcript.render(60, 10)  # follow:start=10,视口显示行 10..19
    transcript.scroll(5)      # 上滚 5 行
    transcript.render(60, 10)  # start=5,视口显示行 5..14
    assert transcript.block_at(0) is blocks[12]
    assert transcript.block_at(2) is blocks[13]
    assert transcript.block_at(8) is blocks[16]
    assert transcript.block_at(10) is None


def test_transcript_iter_lines_preserves_complete_exit_document():
    transcript = Transcript()
    transcript.append(UserBlock("hello"))
    transcript.append(AssistantBlock())
    transcript.blocks[-1].append_text("world")
    lines = transcript.iter_lines(80)
    assert list(lines) == transcript.all_lines(80)


def test_model_full_turn_fold_hides_result_until_expand():
    """完整 turn:工具折叠时结果只显示摘要,展开后完整结果可见(spec「工具调用点击展开」;design D4)。"""
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="你好"))
    model.apply(AgentEvent(EventType.TEXT_DELTA, payload="你好,世界"))
    model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "read", "args": {"file_path": "a.py"}, "id": "c1"}],
        )
    )
    model.apply(AgentEvent(EventType.TOOL_RESULT, payload="第一行\n第二行"))
    model.apply(AgentEvent(EventType.TURN_END))

    tool = next(b for b in model.transcript.blocks if isinstance(b, ToolCallBlock))
    plain = "\n".join(model.transcript.all_lines(60))
    assert "你好,世界" in plain
    assert "Read a.py" in plain  # header 可见
    assert "第一行" not in plain  # 折叠态不展示原始结果
    # 展开后完整结果可见
    tool.toggle_expand()
    plain = "\n".join(model.transcript.all_lines(60))
    assert "第二行" in plain


def test_model_activity_lifecycle_and_out_of_order_tool_results():
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    assert model.activity_visible is True
    model.apply(AgentEvent(EventType.THINKING_DELTA, payload="secret"))
    assert "secret" not in "\n".join(model.transcript.all_lines(60))
    model.apply(AgentEvent(EventType.TOOL_CALL, payload=[
        {"name": "read", "args": {"file_path": "a.py"}, "id": "a"},
        {"name": "read", "args": {"file_path": "b.py"}, "id": "b"},
    ]))
    assert model.activity_visible is False
    model.apply(AgentEvent(EventType.TOOL_RESULT, payload="result-b", metadata={"tool_call_id": "b"}))
    tools = [block for block in model.transcript.blocks if isinstance(block, ToolCallBlock)]
    assert tools[0].result == "" and tools[1].result == "result-b"
    assert model.activity_visible is False
    model.apply(AgentEvent(EventType.TOOL_RESULT, payload="result-a", metadata={"tool_call_id": "a"}))
    assert model.activity_visible is True
    model.apply(AgentEvent(EventType.TEXT_DELTA, payload="done"))
    assert model.activity_visible is False


def test_palette_covers_all_style_tags():
    """词表受控不变式:每个样式标签都有色值,调色板键都在词表内(design D2;T-46)。

    新增样式标签必须进 theme.py 的 __all__ + PALETTE,不得在组件/渲染器里
    硬编码色值——否则后端映射缺失、标签序列断言失效。
    """
    from codeagent.app.tui import theme

    tags = [getattr(theme, name) for name in theme.__all__ if name != "PALETTE"]
    for tag in tags:
        assert tag in theme.PALETTE, f"样式标签 {tag!r} 缺少色值"
    for key in theme.PALETTE:
        assert key in tags, f"调色板键 {key!r} 不在词表 __all__ 中"


def test_footer_info_seeds_status_bar():
    """FooterInfo 装配数据(model/effort/cwd)注入状态栏(design D5)。"""
    model = TuiModel()
    info = FooterInfo(
        model="qwen3.8-max",
        effort="high",
        cwd="/workspace",
    )
    model.status.model = info.model
    model.status.effort = info.effort
    model.status.cwd = info.cwd
    plain = "".join(s.text for s in model.status.render(60)[0])
    assert "qwen3.8-max high · /workspace" in plain


# -- 确认环状态(security-permissions)-----------------------------------------


def test_tool_block_awaiting_and_rejected_states():
    """待确认/已拒绝状态渲染:等待黄色提示,拒绝红色 ✗ + Rejected 摘要。"""
    from codeagent.app.tui.theme import ERROR, WARNING

    block = ToolCallBlock("bash", {"command": "git push"}, call_id="c1")
    block.set_awaiting()
    header = block.render(60)[0]
    plain = "".join(s.text for s in header)
    assert "Awaiting confirmation" in plain
    assert any(s.fg == WARNING for s in header)

    block.set_rejected("[工具执行被拒绝] 用户拒绝执行: 推送远程分支")
    header = block.render(60)[0]
    plain = "".join(s.text for s in header)
    assert header[2].text == "✗" and header[2].fg == ERROR
    assert "Rejected bash" in plain
    # 展开可见拒绝原因
    block.toggle_expand()
    expanded = "".join(s.text for line in block.render(60)[1:] for s in line)
    assert "用户拒绝执行" in expanded


def test_model_confirmation_event_marks_block_awaiting():
    """CONFIRMATION_REQUESTED 事件 → 对应工具块进入等待确认态。"""
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "bash", "args": {"command": "git push"}, "id": "c1"}],
        )
    )
    block = next(b for b in model.transcript.blocks if isinstance(b, ToolCallBlock))
    assert block.awaiting is False
    model.apply(
        AgentEvent(
            EventType.CONFIRMATION_REQUESTED,
            payload={
                "request_id": "cf-r1",
                "tool_call_id": "c1",
                "tool": "bash",
                "summary": "git push",
                "reason": "推送远程分支",
            },
        )
    )
    assert block.awaiting is True
    # 拒绝结果回填后退出等待态并进入拒绝态
    model.apply(
        AgentEvent(
            EventType.TOOL_RESULT,
            payload="[工具执行被拒绝] 用户拒绝执行: 推送远程分支",
            metadata={"tool_call_id": "c1", "error": True, "rejected": True},
        )
    )
    assert block.awaiting is False
    assert block.rejected is True
