"""少量稳定的 TUI 语义快照,不绑定 Textual 终端布局。"""

from codeagent.app.tui.blocks import ToolCallBlock
from codeagent.app.tui.primitives import rich_to_plain
from codeagent.app.tui.status import StatusBar


def test_tool_call_snapshot_keeps_compact_lifecycle_labels():
    block = ToolCallBlock("bash", {"command": "uv run pytest -q"})
    assert rich_to_plain(block.render(60)) == ["▶ · Running command"]

    block.set_result("退出码: 0(耗时 12.3s)\nstdout: ok")
    assert rich_to_plain(block.render(60)) == ["▶ ✓ Ran command (exit 0 · 12.3s)"]


def test_status_bar_snapshot_keeps_reserved_zones():
    bar = StatusBar()
    bar.model = "gpt-5.6-terra"
    bar.effort = "high"
    bar.cwd = "/work"

    line = rich_to_plain(bar.render(60))[0]

    assert "gpt-5.6-t" in line
    assert "│" in line
    assert "上下文 —" in line
