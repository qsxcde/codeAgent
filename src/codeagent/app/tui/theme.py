"""app/tui/theme.py:样式标签词表 + 调色板(hex,非 ANSI)。

设计(design D2):组件只输出**受控样式标签**(数据),不依赖 textual/ANSI;色值
集中在此,后端(textual)把标签映射成 Rich style;换自研引擎只换映射,组件零改动。
测试断言标签序列,不碰 ANSI(spec「样式标签可离线断言」)。

调色板参考 Pi-Agent dark 主题(userMessageBg / toolPendingBg / thinkingText / accent…)。
"""

from __future__ import annotations

__all__ = [
    "PALETTE",
    "TEXT",
    "ACCENT",
    "DIM",
    "TOOL_OUTPUT",
    "SUCCESS",
    "ERROR",
    "WARNING",
    "STATUS_MODEL",
    "STATUS_PATH",
    "USER_BG",
    "USER_PROMPT",
    "ASSISTANT_PROMPT",
    "ACTIVITY",
    "DIFF_ADD",
    "DIFF_REMOVE",
    "DIFF_CONTEXT",
    "BOLD",
    "CODE_BG",
    "HEADING",
    "LIST_BULLET",
    "BLOCK_MARK",
]

# -- 样式标签(受控词表) ---------------------------------------------------

TEXT = "text"               # 正文(Agent 回答)
ACCENT = "accent"           # 强调:工具名、输入 ❯、聚焦边框
DIM = "dim"                 # 次级:思维标题、参数、footer
TOOL_OUTPUT = "tool_output"  # 工具结果
SUCCESS = "success"         # 成功(工具 ✓ / 空闲状态)
ERROR = "error"             # 错误(工具 ✗ / 错误状态)
WARNING = "warning"         # 警告(已取消 / 运行中状态)
STATUS_MODEL = "status_model"  # 状态栏模型/思考强度
STATUS_PATH = "status_path"    # 状态栏工作目录
USER_BG = "user_bg"            # 用户消息整行背景
USER_PROMPT = "user_prompt"    # 用户消息提示符
ASSISTANT_PROMPT = "assistant_prompt"  # 助手正文提示符
ACTIVITY = "activity"          # 等待动画
DIFF_ADD = "diff_add"          # 差异新增行背景
DIFF_REMOVE = "diff_remove"    # 差异删除行背景
DIFF_CONTEXT = "diff_context"  # 差异上下文
BOLD = "bold"                  # Markdown 加粗(引擎映射为字重,色值兜底)
CODE_BG = "code_bg"            # Markdown 行内代码/代码块背景
HEADING = "heading"            # Markdown 标题
LIST_BULLET = "list_bullet"    # Markdown 列表标记
BLOCK_MARK = "block_mark"      # Markdown 代码块围栏(``` / ~~~)

#: 标签 → 色值(hex;目前均为前景色,背景色由后端按需使用词表)。
PALETTE: dict[str, str] = {
    TEXT: "#d4d4d4",
    ACCENT: "#00d7ff",
    DIM: "#666666",
    TOOL_OUTPUT: "#808080",
    SUCCESS: "#b5bd68",
    ERROR: "#cc6666",
    WARNING: "#ffff00",
    STATUS_MODEL: "#f0d9a7",
    STATUS_PATH: "#b5e8ae",
    USER_BG: "#262626",
    USER_PROMPT: "#8a8a8a",
    ASSISTANT_PROMPT: "#c8c8c8",
    ACTIVITY: "#8a8a8a",
    DIFF_ADD: "#183d27",
    DIFF_REMOVE: "#472225",
    DIFF_CONTEXT: "#303030",
    BOLD: "#ffffff",
    CODE_BG: "#2d2d2d",
    HEADING: "#e6c07b",
    LIST_BULLET: "#7fb3d5",
    BLOCK_MARK: "#666666",
}
