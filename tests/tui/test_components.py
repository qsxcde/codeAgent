"""tests/tui/test_components.py:组件树 + TuiModel 事件映射 + 样式标签断言。

对应 spec「消息样式区分」(标签可离线断言)、「用户消息命令记录行」「思考过程独立展示」
「工具调用过程可见」「工具调用点击展开」「双端底部状态条」「alt 屏渲染与滚动」。
"""

from codeagent.app.tui.components import (
    AssistantBlock,
    CancelledBlock,
    ErrorBlock,
    FooterInfo,
    FooterLine,
    Span,
    StatusLine,
    ToolCallBlock,
    Transcript,
    TuiModel,
    UserBlock,
    rich_to_plain,
)
from codeagent.app.tui.theme import (
    ACCENT,
    DIM,
    ERROR,
    SUCCESS,
    TEXT,
    THINKING,
    TOOL_OUTPUT,
    WARNING,
)
from codeagent.core.events import AgentEvent, EventType


class _FakeClock:
    """假时钟:按调用顺序返回预设值(测思考耗时显示,design D3)。"""

    def __init__(self, *values: float) -> None:
        self._values = list(values)

    def __call__(self) -> float:
        return self._values.pop(0)


def test_user_block_command_line():
    """用户消息命令记录行:`❯` accent + 文本 text,无背景(design D2;spec「用户消息背景块」)。"""
    lines = UserBlock("hi").render(10)
    assert lines[0][0].fg == ACCENT and lines[0][0].text == "❯ "
    assert lines[0][1].fg == TEXT and lines[0][1].text == "hi"
    # 不再补齐背景:所有 span 无背景
    assert all(span.bg is None for span in lines[0])


def test_assistant_thinking_expanded_and_styled():
    """思维链不折叠:元信息标题 dim + `│ ` 竖线 + thinking 灰内容(spec「思考过程独立展示」)。"""
    block = AssistantBlock(clock=_FakeClock(0.0, 1.0))
    block.append_thinking("让我想想")
    block.append_text("正文")
    lines = block.render(60)
    assert lines[0][0].fg == DIM and lines[0][0].text == "Thought for 1s"
    assert any(line[0].text == "│ " for line in lines)
    assert any(span.fg == THINKING for line in lines for span in line)
    assert any(span.fg == TEXT for line in lines for span in line)
    # 不折叠:thinking 完整渲染
    assert any("让我想想" in span.text for line in lines for span in line)


def test_assistant_thinking_meta_streaming():
    """思考未结束时仅「思考」,正文到达后补耗时(design D3)。"""
    block = AssistantBlock(clock=_FakeClock(2.0, 5.0))
    block.append_thinking("a")
    assert block.render(60)[0][0].text == "思考"
    block.append_text("b")
    assert block.render(60)[0][0].text == "Thought for 3s"


def test_assistant_thinking_meta_with_tool_count():
    """元信息含工具数,复数形式正确(design D3)。"""
    block = AssistantBlock(clock=_FakeClock(1.0, 4.0))
    block.append_thinking("a")
    block.append_text("b")
    block.tool_count = 2
    assert block.render(60)[0][0].text == "Thought for 3s · 2 tool calls"
    block.tool_count = 1
    assert block.render(60)[0][0].text == "Thought for 3s · 1 tool call"


def test_tool_call_folded_by_default():
    """工具默认折叠:折叠符 ▶ + 状态图标 + accent 名 + 参数摘要(design D4)。"""
    block = ToolCallBlock("read", {"file_path": "a.py"})
    block.set_result("file content")
    lines = block.render(60)
    assert len(lines) == 1  # 只 header,结果隐藏
    header = lines[0]
    assert header[0].text == "▶" and header[0].fg == DIM
    assert header[2].text == "✓" and header[2].fg == SUCCESS
    assert any(s.fg == ACCENT and s.text == "read" for s in header)
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


def test_tool_call_args_summary():
    """参数摘要:bash 命令直显,不含 JSON 键名(design D4)。"""
    block = ToolCallBlock("bash", {"command": "uv run pytest -q"})
    plain = "".join(s.text for s in block.render(60)[0])
    assert "uv run pytest -q" in plain
    assert "{" not in plain and "command" not in plain


def test_tool_call_result_summary():
    """结果摘要:bash 退出码/耗时、write 字节、edit 处数;解析失败回退首行(design D4)。"""
    bash = ToolCallBlock("bash", {})
    bash.set_result("退出码: 0(耗时 12.3s)\nstdout: ok")
    assert "exit 0 · 12.3s" in "".join(s.text for s in bash.render(60)[0])

    write = ToolCallBlock("write", {})
    write.set_result("已写入 a.py(120 字节)")
    assert "120 B" in "".join(s.text for s in write.render(60)[0])

    edit = ToolCallBlock("edit", {})
    edit.set_result("已替换 2 处: a.py")
    assert "2 处" in "".join(s.text for s in edit.render(60)[0])

    other = ToolCallBlock("grep", {})
    other.set_result("第一行\n第二行")
    plain = "".join(s.text for s in other.render(60)[0])
    assert "第一行" in plain and "第二行" not in plain  # 折叠态仅摘要


def test_error_and_cancelled_spans():
    assert ErrorBlock("boom").render(60)[0][0].fg == ERROR
    assert CancelledBlock().render(60)[0][0].fg == WARNING


def test_status_line_status_colors():
    """状态栏状态色:运行 warning(design D3;spec「状态栏状态色」)。"""
    status = StatusLine()
    status.status = "RUNNING"
    status.model = "deepseek"
    status.usage = "↑10 ↓5"
    line = status.render(60)[0]
    assert line[0].fg == WARNING and "[RUNNING]" in line[0].text
    assert "deepseek" in line[0].text and "↑10" in line[0].text


def test_footer_line_two_sides_right_aligned():
    """footer 双端:左状态/快捷键 + 右 model · effort,整行宽右对齐(design D5;spec「双端底部状态条」)。"""
    footer = FooterLine()
    footer.model = "qwen3.8-max"
    footer.effort = "high"
    line = footer.render(40)[0]
    assert "● ready · Esc 退出" in line[0].text
    assert line[-1].text == "qwen3.8-max · high"
    assert len("".join(s.text for s in line)) == 40  # 右对齐:补齐到整行宽


def test_footer_line_truncates_right_on_narrow_width():
    """宽度不足时右端优先截断,左端快捷键保持可见(design D5)。"""
    footer = FooterLine()
    footer.model = "a-very-long-model-name"
    footer.effort = "high"
    line = footer.render(20)[0]
    plain = "".join(s.text for s in line)
    assert len(plain) == 20
    assert "● ready · Esc 退出" in plain
    assert "a-very-long-model-name" not in plain


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
    assert transcript.block_at(1) is tool
    assert transcript.block_at(99) is None


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
    assert "read" in plain  # header 可见
    assert "第一行" in plain  # 折叠态:结果摘要可见
    assert "第二行" not in plain  # 折叠态:完整结果隐藏
    # 展开后完整结果可见
    tool.toggle_expand()
    plain = "\n".join(model.transcript.all_lines(60))
    assert "第二行" in plain


def test_footer_info_seeds_model_footer():
    """FooterInfo 装配数据注入 TuiModel.footer(design D5)。"""
    model = TuiModel()
    info = FooterInfo(model="qwen3.8-max", effort="high")
    model.footer.model = info.model
    model.footer.effort = info.effort
    plain = "".join(s.text for s in model.footer.render(40)[0])
    assert "qwen3.8-max · high" in plain


def test_editor_renders_text():
    from codeagent.app.tui.components import Editor

    editor = Editor()
    editor.text = "hi"
    assert rich_to_plain(editor.render(60)) == ["▍ hi"]
