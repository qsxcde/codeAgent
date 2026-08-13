## Why

restore-tui 落地的 MVP 聊天区是**纯文本标记**(`你:` / `[思考]` / `· read()` / `[IDLE]`),无颜色、无样式区分,长对话可读性差。按 Pi-Agent(`earendil-works/pi`)与 Claude Code 的样式体系做视觉美化:不同消息类型(用户 / Agent 回答 / 思维链 / 工具调用 / 错误 / 取消)各有明确视觉语言,输入框升级为 Claude 风格带边框 box。样式以「标签段」贯穿组件→后端,保持组件引擎无关、离线可测。

## What Changes

- **组件 render 契约升级**:`list[str]` → `list[RichLine]`(``RichLine = list[Segment]``,``Segment = (style_tag, text)``),支持背景标签;组件只输出**受控样式标签**(不是 ANSI),主题映射在后端(design 机制 B);
- **六类消息视觉区分**(参考 pi 色值 + Claude 简约布局):
  - **用户**:`#343541` 背景块(整行同背景),去 `>` 前缀;
  - **Agent 回答**:默认 `text` 色,无背景;
  - **思维链**:`thinking` 灰,`▸ 思考` 标题(dim),**始终展开不折叠**;
  - **工具调用**:状态色图标(`·` 灰 / `✓` success 绿 / `✗` error 红)+ 工具名 `accent` + 参数 `dim` + 结果 `tool_output` 灰;**默认折叠**(仅 header),**点击 header 展开/折叠**;
  - **错误**:`error` 红; **取消**:`warning` 黄;
- **状态栏**:运行黄 / 空闲绿 / 错误红,模型与用量 dim;
- **输入框 Claude 风格**:带边框 box(`❯` accent prompt + 文本 text + placeholder dim),聚焦时边框 accent、失焦 borderMuted,`Enter` 发送、`Shift+Enter` 换行、随内容增高;
- **ToolCallBlock 加折叠状态**:`expanded`(默认 False)+ `toggle_expand(id)` 入口;textual 后端把「点击工具 header」路由为切换;
- **BREAKING**:无——消息/输入仍是既有行为契约(发送、渲染、打断),本轮是渲染样式与输入形态增强;组件 render 契约内部升级,对外工具/会话零改动。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tui`:`对话输入与回复渲染`(用户消息背景块、Claude 风格输入框)、`流式回复渲染`(思维链不折叠、工具调用默认折叠+点击展开)、新增 `消息样式区分` 需求(调色板 + 各消息类型样式契约)。

## Impact

- **受影响代码**:
  - `src/codeagent/app/tui/components.py` —— `Segment`/`RichLine` 模型、各块输出样式标签、`ToolCallBlock.expanded` + `toggle_expand`;
  - 新增 `src/codeagent/app/tui/theme.py`(或并入 backend)—— 样式标签 → 颜色的主题映射;
  - `src/codeagent/app/tui/textual_backend.py` —— 把 `RichLine` 渲染为富文本(含背景)、工具 header 点击事件路由;
  - `src/codeagent/app/tui/view.py` —— 点击 → `toggle_expand` + 重渲染;
  - `tests/tui/` —— 断言样式标签序列(不碰 ANSI);
- **不受影响**:`core/`、`session/`、`tools/`、`ai/`、headless `app/main.py` 与 `--tui` 入口零改动;
- **依赖**:零新增(textual 已在 restore-tui 引入);
- **验收口径**:全量 `uv run pytest` 保持绿色(现 240 项 + 新增用例);组件离线断言标签;`--tui` 人工验收:六类消息视觉区分、工具点击折叠、Claude 风格输入框。

> 设计决策来源:Pi-Agent 主题 token 模型(`userMessageBg`/`toolPendingBg`/`thinkingText`/`accent`…具体色值 `#00d7ff`/`#b5bd68`/`#cc6666`/`#343541`)× Claude Code 简约无背景布局。完整设计见 `design.md`。
