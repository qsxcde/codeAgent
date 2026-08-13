"""tests/tui/test_components.py:组件树 + TuiModel 事件映射 + 样式标签断言。

对应 spec「消息样式区分」(标签可离线断言)、「用户消息背景块」「思考过程独立展示」
「工具调用过程可见」「工具调用点击展开」「alt 屏渲染与滚动」。
"""

from codeagent.app.tui.components import (
    AssistantBlock,
    CancelledBlock,
    ErrorBlock,
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
    USER_BG,
    WARNING,
)
from codeagent.core.events import AgentEvent, EventType


def test_user_block_background_span():
    """用户消息渲染为背景块:text 前景 + user_bg 背景,补齐到宽(spec「用户消息背景块」)。"""
    lines = UserBlock("hi").render(10)
    assert lines[0][0].fg == TEXT and lines[0][0].bg == USER_BG
    assert lines[0][0].text == "hi"
    # 补齐段:纯背景空格
    assert lines[0][-1].bg == USER_BG and lines[0][-1].fg is None


def test_assistant_thinking_expanded_and_styled():
    """思维链不折叠,▸ 标题 dim + 内容 thinking 灰(spec「思考过程独立展示」)。"""
    block = AssistantBlock()
    block.append_thinking("让我想想")
    block.append_text("正文")
    lines = block.render(60)
    assert lines[0][0].fg == DIM and lines[0][0].text == "▸ 思考"
    assert any(span.fg == THINKING for line in lines for span in line)
    assert any(span.fg == TEXT for line in lines for span in line)
    # 不折叠:thinking 完整渲染
    assert any("让我想想" in span.text for line in lines for span in line)


def test_tool_call_folded_by_default():
    """工具默认折叠:只渲染 header(状态色图标 + accent 名 + dim 参数)(spec「工具调用过程可见」)。"""
    block = ToolCallBlock("read", '{"file_path": "a.py"}')
    block.set_result("file content")
    lines = block.render(60)
    assert len(lines) == 1  # 只 header,结果隐藏
    fgs = [s.fg for s in lines[0]]
    assert SUCCESS in fgs and ACCENT in fgs and DIM in fgs


def test_tool_call_expand_shows_result():
    """点击展开后结果行出现,样式 tool_output(spec「工具调用点击展开」)。"""
    block = ToolCallBlock("read", "")
    block.set_result("file content")
    block.toggle_expand()
    lines = block.render(60)
    assert len(lines) == 2
    assert lines[1][0].fg == TOOL_OUTPUT and "file content" in lines[1][0].text


def test_tool_call_error_icon():
    block = ToolCallBlock("bash", "")
    block.set_result("退出码 1", error=True)
    icon = block.render(60)[0][0]
    assert icon.fg == ERROR and icon.text == "✗"


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
    tool = ToolCallBlock("read", "")
    transcript.append(user)
    transcript.append(tool)
    transcript.render(60, 10)
    assert transcript.block_at(0) is user
    assert transcript.block_at(1) is tool
    assert transcript.block_at(99) is None


def test_model_full_turn_fold_hides_result_until_expand():
    """完整 turn:工具默认折叠时结果隐藏,展开后可见(spec「工具调用点击展开」)。"""
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="你好"))
    model.apply(AgentEvent(EventType.TEXT_DELTA, payload="你好,世界"))
    model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "read", "args": {"file_path": "a.py"}, "id": "c1"}],
        )
    )
    model.apply(AgentEvent(EventType.TOOL_RESULT, payload="内容"))
    model.apply(AgentEvent(EventType.TURN_END))

    tool = next(b for b in model.transcript.blocks if isinstance(b, ToolCallBlock))
    plain = "\n".join(model.transcript.all_lines(60))
    assert "你好,世界" in plain
    assert "read" in plain  # header 可见
    assert "内容" not in plain  # 折叠:结果隐藏
    # 展开后结果可见
    tool.toggle_expand()
    plain = "\n".join(model.transcript.all_lines(60))
    assert "内容" in plain


def test_editor_renders_text():
    from codeagent.app.tui.components import Editor

    editor = Editor()
    editor.text = "hi"
    assert rich_to_plain(editor.render(60)) == ["▍ hi"]
