## Why

当前 TUI 是"聊天气泡"布局模型:用户消息渲染为全宽灰背景块、输入区是占剩余高度的双层边框大表单、思维链平铺原始大段文本、工具参数以裸 JSON 展示、底部只有一行快捷键提示。与参考目标(Claude Code / Pi 风格的**终端操作记录界面**)相比,差距是布局模型与信息层级,不是配色:目标界面里用户输入是低对比命令记录、输入区是固定单行 composer、工具调用是紧凑可扫描的操作日志、底部是双端状态条。本轮把布局与样式收敛到目标形态;Markdown 渲染与滚动/点击交互留到下一轮。

## What Changes

- **输入框重构为单行 composer**:`_InputBox` 从自由高度 `Vertical` 容器 + 双重边框改为固定 1~2 行,`❯` prompt 与 Input 同行,上下用细分隔线与 transcript / footer 区隔;不再占剩余高度。
- **用户消息改为命令记录行**:去掉全宽 `USER_BG` 背景补齐,改为低对比命令记录(`› 文本`),与 agent 回复在视觉上仍可区分。
- **思维链弱化(保持始终展开)**:从"平铺原文"改为元信息标题(`Thought for Ns · N tool calls`)+ 左侧竖线 + 灰色缩进内容;元数据由 TUI 本地用事件时间戳测量,不改 core。
- **工具调用块样式升级**:header 增加 `▶`/`▼` 折叠状态提示;参数用工具专用摘要(`read src/…` 而非 `{"file_path": …}`);折叠态显示结果摘要(bash 退出码/耗时、write 字节数等),展开显示全文。
- **Footer 双端布局**:左端状态/快捷键,右端 `model · effort`。
- **状态栏契约修复**:`set_status` / `set_footer` 从 `str` 升级为 `RichLine`,修复 `_flush_render` 把富样式当字符串传递的 bug。

**不在本轮范围**(下一轮):Agent 正文 Markdown 渲染、滚轮/键盘滚动、视口点击命中(block_at 偏移)修复。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `tui`:用户消息渲染(背景块→命令记录行)、输入框(带边框区域→单行 composer)、思维链展示样式、工具调用块样式(折叠提示/参数摘要/结果摘要)、状态栏与 footer(双端布局 + 富样式契约)。

## Impact

- `src/codeagent/app/tui/textual_backend.py`:`_InputBox` 布局重构、composer 分隔线、footer 双端渲染、`set_status`/`set_footer` 富样式实现。
- `src/codeagent/app/tui/components.py`:`UserBlock` / `AssistantBlock` / `ToolCallBlock` / `StatusLine` 渲染逻辑与摘要 formatter。
- `src/codeagent/app/tui/backend.py`:`TuiBackend` 端口契约(`set_status(text: str)` → `RichLine`)。
- `src/codeagent/app/tui/view.py`:`_flush_render` 传值修正。
- `src/codeagent/app/tui/theme.py`:新增样式标签(折叠符、结果摘要、footer 等)。
- `tests/tui/test_components.py`、`tests/tui/test_view.py`:断言随新样式标签与布局更新,保持全量测试通过。
