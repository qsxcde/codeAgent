## 1. 主题与段模型

- [x] 1.1 新建 `src/codeagent/app/tui/theme.py`:`StyleTag` 词表 + `PALETTE` 色值(design D2;hex,非 ANSI;`user_bg` 为背景色)
- [x] 1.2 `components.py` 升级渲染契约:`Segment = tuple[StyleTag, str]`、`RichLine = list[Segment]`,组件 `render(width) -> list[RichLine]`;`_wrap` 改为对纯文本换行产出单样式行(`_wrap_rich`)(design D1)

## 2. 组件样式化

- [x] 2.1 UserBlock 输出 `user_bg` 背景段 + `text` 文字段(spec「用户消息背景块」);AssistantBlock 输出 `dim` `▸ 思考` 标题 + `thinking` 内容 + `text` 正文,思考**始终展开不折叠**(spec「思考过程独立展示」)
- [x] 2.2 ToolCallBlock:header = 状态色图标(`·` dim / `✓` success / `✗` error)+ `accent` 工具名 + `dim` 参数;结果行 `tool_output`;加 `expanded: bool = False` + `toggle_expand()`,折叠时只渲染 header(spec「工具调用摘要可见」「工具调用点击展开」)
- [x] 2.3 ErrorBlock / CancelledBlock / StatusLine:分别输出 `error` / `warning` / 状态色(`RUNNING` warning / `IDLE` success / `ERROR` error)+ 模型用量 `dim`(spec「状态栏状态色」)
- [x] 2.4 `Transcript`:`render()` 缓存「视口行 → 所属块」`_line_blocks`;新增 `block_at(relative_y) -> Component | None`(design D4)

## 3. 后端富渲染与点击路由

- [x] 3.1 `textual_backend.render` 把 `RichLine` 渲染为 Rich `Text`(标签→色值,`bg=user_bg` 背景),不再依赖字面量 markup(design D2/D6)
- [x] 3.2 后端把「点击 transcript 某行」传给 `TuiApp`;`TuiApp` 经 `block_at` 得块,若为 ToolCallBlock 则 `toggle_expand()` + 重渲染(design D4)
- [x] 3.3 输入框 Claude 风格:带边框容器(聚焦 `accent` / 失焦 `muted`)+ `❯` accent Label + `Input`(placeholder dim)+ footer `Enter=发送`(design D5;spec「Claude 风格输入框」)

## 4. 视图接线

- [x] 4.1 `view`:`on_click(line)` 处理器 + 重渲染;`exit_document` 仍以纯文本输出(剥离样式标签)(design D6)

## 5. 测试 `tests/tui/`

- [x] 5.1 组件渲染断言**标签序列**(各块含用户背景/思维/工具状态色,不碰 ANSI;spec「样式标签可离线断言」)
- [x] 5.2 工具折叠:默认折叠(只 header)、toggle 展开(结果行出现)、`block_at` 命中(design D4)
- [x] 5.3 状态栏状态色切换、输入框形态(纯样式层断言)
- [x] 5.4 全量 `uv run pytest` 通过(现 240 + 新增,无新失败)

## 6. 收尾

- [x] 6.1 更新需求分析 FR-1 相关状态与 v0.1 迭代文档:TUI 样式美化落地说明
- [x] 6.2 归档本 change 至 `openspec/changes/archive/`,specs 同步回主 `openspec/specs/tui/spec.md`
