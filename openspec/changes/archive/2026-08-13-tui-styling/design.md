## Context

动机与范围见 `proposal.md`。现状要点:

- `restore-tui` 落地的 `app/tui/`:组件纯 `render(width) -> list[str]`(plain 标记)、`TuiBackend` 端口、textual 后端(`Static markup=False` 按字面量显示)、`TuiApp` 订阅事件 + 合并渲染;
- 六类消息当前用文本标记区分(`你:` / `[思考]` / `· read()` / `[错误]` / `[已取消]` / `[IDLE]`),无颜色、无背景、无折叠;
- 输入框是 `▍ {text}` 裸行(textual `Input` 无边框);
- 测试哲学:组件离线可测、断言行为不实现、平台无关。

设计参照:Pi-Agent 主题 token 模型(具体色值来自 `packages/coding-agent/.../theme/dark.json`)× Claude Code 简约布局。样式以「受控标签段」贯穿组件→后端,组件保持引擎无关。

## Goals / Non-Goals

**Goals:**
- 六类消息视觉可区分:用户背景块 / Agent 默认 / 思维灰不折叠 / 工具状态色+默认折叠+点击展开 / 错误红 / 取消黄;
- 状态栏运行黄 / 空闲绿 / 错误红;
- 输入框 Claude 风格带边框 box;
- 样式以「标签段」模型实现,组件仍引擎无关、离线可测(断言标签不碰 ANSI)。

**Non-Goals:**
- 斜杠命令 / 模糊补全 / 命令选择器(仍登记下一迭代,与 restore-tui 一致);
- 思维链折叠(用户明确要求不折叠);
- 多行输入 `Shift+Enter`(记录为下一迭代增强;本轮是边框形态);
- Markdown 富文本渲染(加粗/代码高亮,下一迭代);
- 会话 / 工具 / headless 任何改动。

## Decisions

### D1. 样式标签段模型(render 契约升级)

```python
StyleTag = str  # 受控词表
Segment  = tuple[StyleTag, str]
RichLine = list[Segment]

# 组件 render(width) -> list[RichLine]
```

- **为什么**:行内分段着色(工具块「状态色图标 + accent 名 + dim 参数」同行异色)+ 背景(用户块)都要求段级样式;标签是数据,组件不依赖 textual/ANSI,离线断言标签序列(spec「样式标签可离线断言」);
- **换行处理**:`_wrap` 对纯文本换行,产出**单样式行**(换行后的行只带一种样式)——多行正文/结果行不需要行内多色;header 行短、不换行;
- **备选**:Rich markup 字符串(组件耦合 Rich 语法、字面量 `[` 转义)、后端按块类上色(无法同行异色)。

### D2. 调色板与主题映射(后端持有)

`app/tui/theme.py` 定义标签词表 + 色值(hex,非 ANSI——组件测试可引用,后端消费):

```python
PALETTE: dict[str, str] = {
    "text": "#d4d4d4", "accent": "#00d7ff", "dim": "#666666",
    "thinking": "#808080", "tool_output": "#808080",
    "success": "#b5bd68", "error": "#cc6666", "warning": "#ffff00",
    "user_bg": "#343541",  # 背景色
}
```

- textual 后端把 Segment → Rich `Text` span(`fg=色值` / `bg=user_bg`),**用 Text 对象而非 markup 字符串**——规避字面量 `[` 被当 markup 解析的问题;
- 窄终端降级:颜色由 textual/终端按支持度映射(真彩 → 256 → 基础)。

### D3. 各块样式(标签分配)

| 块 | 样式 |
|---|---|
| UserBlock | 整行 `user_bg` 背景段 + `text` 文字段 |
| AssistantBlock | body 全 `text`;thinking:`dim` `▸ 思考` 标题行 + `thinking` 内容行 |
| ToolCallBlock | header:`状态色`图标(`·` dim / `✓` success / `✗` error)+ `accent` 工具名 + `dim` 参数;结果行 `tool_output` |
| ErrorBlock | `error` |
| CancelledBlock | `warning` |
| StatusLine | 状态色(RUNNING warning / IDLE success / ERROR error)+ 模型与用量 `dim` |

### D4. 工具调用折叠(默认折叠 + 点击展开)

- `ToolCallBlock.expanded: bool = False` + `toggle_expand()`;折叠时只渲染 header 行,展开才渲染结果行;
- **点击路由**:`Transcript` 在 `render()` 时缓存「视口行 → 所属块」映射 `_line_blocks`;新增 `block_at(relative_y) -> Component | None`;textual 后端把「点击 transcript 某行」传给 `TuiApp`,`TuiApp` 查 `block_at` 得块 → 若为 ToolCallBlock 则 `toggle_expand()` + 重渲染;
- 折叠行仍显示状态(结果返回后 header 状态色更新,pending→done/error)。

### D5. 输入框 Claude 风格

- textual:带边框容器(聚焦 `border-accent` / 失焦 `border-muted`),内部 `❯`(accent `Label`)+ `Input`(placeholder dim,文本 text);
- `Enter` 提交(现有 `on_input_submitted` 保留);footer 显示 `Enter=发送`;
- 多行 `Shift+Enter` 与输入框随内容增高 → 下一迭代(TextArea 评估)。

### D6. 渲染管线调整

- `view._flush_render`:组件产 `list[RichLine]` → `backend.render(lines)`(lines 现在是富行);
- `textual_backend.render`:`RichLine` → Rich `Text`(D2 映射)→ `Static.update(...)`;`markup=False` 保持但改用 `Text` 对象后不再依赖字面量语义;
- 退出文档(`exit_document`):仍以纯文本输出(剥离样式标签,或按 text 色渲染)——保持可复制性。

## Risks / Trade-offs

- **[render 契约升级触及全部组件与测试]** → 组件改为输出标签段,测试改为断言标签序列;净收益(样式可测、不再 plain 字符串);
- **[用户背景块在长对话占空间]** → 用户明确选择;每行同背景、wrap 到宽,视觉重量可控;
- **[工具点击命中精度]** → `block_at` 基于渲染时行映射,MVP 足够;长行 wrap 时一行可能映射到多块的分段位置,取该行首块即可;
- **[富文本转义/解析隐患]** → 用 Rich `Text` 对象(显式 span 样式)而非 markup 字符串,规避字面量 `[` 被解析;
- **[窄终端真彩降级]** → 颜色由 textual 按终端能力映射;标签→语义不变,降级不失可区分性(图标/背景仍区分)。

## Migration Plan

- 顺序:theme.py(标签+色值)→ components 改输出 RichLine(各块样式、折叠状态)→ Transcript 行映射 + block_at → backend 富渲染 + 点击路由 → view 接线 → 测试重写;
- 门槛:全量 `uv run pytest` 绿(现 240 + 新增);`--tui` 人工验收:六类可区分、工具点击折叠、Claude 输入框;
- 回滚:`git revert`;组件契约升级不影响会话/工具,无跨层耦合;
- 依赖零新增。

## Open Questions

无(多行输入、Markdown 富文本已记为下一迭代增强,不改变本 spec 或任务拆解)。
