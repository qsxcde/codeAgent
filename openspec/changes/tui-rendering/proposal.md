## Why

Agent 回复目前是纯文本渲染:代码块、列表、标题、行内代码混在正文里难以阅读;同时 Transcript 的滚动语义(follow/scroll)已在组件层实现,但 `TuiBackend` 没有滚动输入端口,滚轮与 PageUp/PageDown 无法操作历史(§12.2 TUI 增强两项:T-46 Markdown 渲染、T-47 滚动交互)。

## What Changes

- **Markdown 正文渲染**:`AssistantBlock` 正文经注入的解析器(无状态纯函数,仿 `clock` 注入模式)渲染为受控样式标签——加粗/行内代码/列表/标题/代码块;流式期间每帧全量重解析(方案 A,body 通常 ≤ 几 KB,满足 ≥30fps 的 NFR-P5);未闭合结构宽容处理(不渲染背景),终态自然完整;超长 body 退化为纯文本。
- **滚动交互**:`TuiBackend` 增 `on_scroll` 端口(相对行号增量);textual 后端转发滚轮事件与 PageUp/PageDown;`view.py` 分派到 `Transcript.scroll / scroll_to_bottom`(上滚解除跟随、滚回底部恢复,组件层语义已实现);输入框聚焦时按键归属显式分派(PageUp/PageDown 不被 TextArea 吞掉)。
- **样式标签扩展**:`theme.py` 词表新增 code/heading 等标签,后端映射同步;词表保持受控(测试断言标签序列不变式)。
- 无 **BREAKING** 变更;`TuiBackend` 端口仅增补 `on_scroll`。

## Capabilities

### New Capabilities

无(均为既有 `tui` 能力的扩展)。

### Modified Capabilities

- `tui`:新增「Markdown 正文渲染」requirement;「alt 屏渲染与滚动」requirement 补充滚动输入来源场景(滚轮 / PageUp / PageDown)。

## Impact

- `src/codeagent/app/tui/backend.py`:`on_scroll` 端口与 `ScrollHandler` 类型。
- `src/codeagent/app/tui/textual_backend.py`:`_Transcript` 滚轮转发、`_InputArea` 按键归属、App 层 PageUp/PageDown 绑定。
- `src/codeagent/app/tui/components.py`:`AssistantBlock` Markdown 渲染(注入 `md_renderer`)、`Transcript` 无改动(滚动语义已就位)。
- `src/codeagent/app/tui/view.py`:滚动分派。
- `src/codeagent/app/tui/theme.py`:样式标签词表扩展。
- `tests/tui/test_components.py`、`test_view.py`:Markdown 标签序列断言、滚动分派与 follow 翻转断言。
