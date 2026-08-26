"""TUI 渲染层兼容入口。

职责已拆分到 primitives、blocks、transcript、status 和 model；保留此入口
用于内部迁移期间的稳定导入。新代码应直接依赖对应职责模块。
"""

from codeagent.app.tui.blocks import (
    ActivityBlock, AssistantBlock, CancelledBlock, ErrorBlock,
    ToolCallBlock, UserBlock,
)
from codeagent.app.tui.model import TuiModel
from codeagent.app.tui.primitives import (
    Component, RichLine, Span, _cell_width, _format_token_count, _plain, _seg, _truncate,
    _truncate_spans, _visible_user_content, _wrap, _wrap_rich, rich_to_plain,
)
from codeagent.app.tui.runtime import RuntimePhase, RuntimeReducer, RuntimeSnapshot
from codeagent.app.tui.status import FooterInfo, StatusBar
from codeagent.app.tui.transcript import Transcript

__all__ = [
    "Span", "RichLine", "Component", "UserBlock", "AssistantBlock",
    "ActivityBlock", "ToolCallBlock", "ErrorBlock", "CancelledBlock",
    "Transcript", "StatusBar", "FooterInfo", "TuiModel", "RuntimePhase",
    "RuntimeSnapshot", "RuntimeReducer",
]
