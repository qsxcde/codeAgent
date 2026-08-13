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
    "THINKING",
    "TOOL_OUTPUT",
    "SUCCESS",
    "ERROR",
    "WARNING",
    "USER_BG",
    "BORDER",
    "BORDER_MUTED",
]

# -- 样式标签(受控词表) ---------------------------------------------------

TEXT = "text"               # 正文(Agent 回答)
ACCENT = "accent"           # 强调:工具名、输入 ❯、聚焦边框
DIM = "dim"                 # 次级:思维标题、参数、footer
THINKING = "thinking"       # 思维内容
TOOL_OUTPUT = "tool_output"  # 工具结果
SUCCESS = "success"         # 成功(工具 ✓ / 空闲状态)
ERROR = "error"             # 错误(工具 ✗ / 错误状态)
WARNING = "warning"         # 警告(已取消 / 运行中状态)
USER_BG = "user_bg"         # 用户消息背景
BORDER = "border"           # 聚焦边框
BORDER_MUTED = "border_muted"  # 失焦边框

#: 标签 → 色值(hex;`user_bg` 是背景色,其余为前景色)。
PALETTE: dict[str, str] = {
    TEXT: "#d4d4d4",
    ACCENT: "#00d7ff",
    DIM: "#666666",
    THINKING: "#808080",
    TOOL_OUTPUT: "#808080",
    SUCCESS: "#b5bd68",
    ERROR: "#cc6666",
    WARNING: "#ffff00",
    USER_BG: "#343541",
    BORDER: "#00d7ff",
    BORDER_MUTED: "#505050",
}
