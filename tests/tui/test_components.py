"""tests/tui/test_components.py:组件树 + TuiModel 事件映射(纯离线,不 import textual)。

对应 spec「组件渲染离线可测」「流式回复渲染」「工具调用过程可见」「alt 屏渲染与滚动」
「状态栏实时反馈」。
"""

from codeagent.app.tui.components import (
    AssistantBlock,
    CancelledBlock,
    Editor,
    ErrorBlock,
    StatusLine,
    ToolCallBlock,
    Transcript,
    TuiModel,
    UserBlock,
)
from codeagent.core.events import AgentEvent, EventType


def test_user_block_renders_prompt():
    lines = UserBlock("hello").render(60)
    assert lines == ["你: hello"]


def test_assistant_thinking_and_body_rendered_distinct():
    block = AssistantBlock()
    block.append_thinking("让我想想")
    block.append_text("正文")
    lines = block.render(60)
    assert lines[0] == "[思考]"
    assert "让我想想" in lines
    assert "正文" in lines


def test_assistant_only_thinking_shows_placeholder():
    """仅有思考、正文未出时渲染进行中占位(对应 spec「思考过程独立展示」)。"""
    block = AssistantBlock()
    block.append_thinking("思考中")
    lines = block.render(60)
    assert "…" in lines


def test_tool_call_status_transition():
    """工具块状态流转 pending → done,结果可见(spec「工具调用过程可见」)。"""
    block = ToolCallBlock("read", '{"file_path": "a.py"}')
    lines = block.render(60)
    assert lines[0].startswith("· read(")
    block.set_result("file content")
    lines = block.render(60)
    assert lines[0].startswith("✓ read(")
    assert "file content" in lines


def test_error_and_cancelled_blocks():
    assert ErrorBlock("boom").render(60)[0] == "[错误]"
    assert CancelledBlock().render(60) == ["[已取消]"]


def test_status_line_usage():
    status = StatusLine()
    status.status = "RUNNING"
    status.model = "deepseek"
    status.usage = "↑10 ↓5 思考3"
    line = status.render(60)[0]
    assert "[RUNNING]" in line and "deepseek" in line and "↑10" in line


def test_transcript_follow_end():
    """跟底 / 上滚解跟随 / 回底恢复(spec「alt 屏渲染与滚动」三场景)。"""
    transcript = Transcript()

    class _FakeBlock:
        def render(self, width):
            return [f"line{i}" for i in range(30)]

    transcript.append(_FakeBlock())
    # 跟底:视口显示最后 height 行
    view = transcript.render(60, 10)
    assert len(view) == 10
    assert view[0] == "line20"  # 最新在底部
    assert transcript.follow is True
    # 上滚解除跟随
    transcript.scroll(5)
    assert transcript.follow is False
    view = transcript.render(60, 10)
    assert view[0] == "line15"
    # 滚回底部恢复跟随
    transcript.scroll_to_bottom()
    assert transcript.follow is True


def test_model_full_turn_event_mapping():
    """脚本事件序列 → 块序列(对应 spec「流式回复渲染」)。"""
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="你好"))
    model.apply(AgentEvent(EventType.THINKING_DELTA, payload="想"))
    model.apply(AgentEvent(EventType.TEXT_DELTA, payload="你好,世界"))
    model.apply(
        AgentEvent(
            EventType.TOOL_CALL,
            payload=[{"name": "read", "args": {"file_path": "a.py"}, "id": "c1"}],
        )
    )
    model.apply(AgentEvent(EventType.TOOL_RESULT, payload="内容"))
    model.apply(AgentEvent(EventType.TURN_END))

    assert model.running is False
    assert model.status.status == "IDLE"
    kinds = [type(b).__name__ for b in model.transcript.blocks]
    assert kinds == ["UserBlock", "AssistantBlock", "ToolCallBlock"]
    lines = model.transcript.all_lines(60)
    assert "你: 你好" in lines
    assert "你好,世界" in lines
    assert "✓ read(" in "\n".join(lines)
    assert "内容" in lines


def test_model_run_cancelled_adds_block():
    model = TuiModel()
    model.apply(AgentEvent(EventType.SESSION_STARTED, payload="x"))
    model.apply(AgentEvent(EventType.RUN_CANCELLED))
    assert model.running is False
    assert model.status.status == "IDLE"
    assert any(isinstance(b, CancelledBlock) for b in model.transcript.blocks)


def test_model_error_updates_status():
    model = TuiModel()
    model.apply(AgentEvent(EventType.ERROR, payload="图运行出错"))
    assert model.status.status == "ERROR"
    assert any(isinstance(b, ErrorBlock) for b in model.transcript.blocks)


def test_editor_renders_text():
    editor = Editor()
    editor.text = "hi"
    assert editor.render(60)[0] == "▍ hi"
