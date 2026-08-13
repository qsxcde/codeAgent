## Context

动机见 proposal.md「Why」。当前 TUI 是聊天气泡模型:输入框 `_InputBox` 为自由高度 `Vertical` 容器 + 双重边框(`textual_backend.py:62-83`),用户消息是全宽背景块(`components.py:103-118`),思维链平铺原文(`components.py:121-152`),工具参数裸 JSON(`components.py:155-191`),footer 单行提示(`textual_backend.py:102-103`)。另有一个契约不一致:`StatusLine.render()` 返回 `RichLine`,`_flush_render` 却当 `str` 传给 `set_status`(`view.py:99` vs `backend.py:38`),状态栏富样式从未真正生效。

本轮只做布局 + 样式;Markdown 渲染与滚动/点击交互留到下一轮(见 proposal 范围)。

## Goals / Non-Goals

**Goals:**
- 输入区收敛为固定单行 composer(上下细分隔线,`❯` 与输入同行);
- 用户消息改为低对比命令记录行(无全宽背景);
- 思维链保持始终展开,但弱化为元信息标题 + 竖线缩进;
- 工具块 header 增加 `▶/▼` 折叠提示、参数摘要与结果摘要;
- footer 双端布局(左状态/快捷键,右 model · effort);
- 修复 `set_status`/`set_footer` 富样式契约(`RichLine`);
- 全程保持组件引擎无关、离线可测(样式标签断言)。

**Non-Goals:**
- Agent 正文 Markdown 渲染(下一轮);
- 滚轮/键盘滚动、视口点击命中修复(下一轮);
- 工具结果 diff 渲染(edit/write 结果无 diff 内容,摘要即可);
- 主题切换、配置化配色。

## Decisions

### D1: 输入区重构为 Dock 布局(composer 行)

`_TextualApp` 的 compose 顺序改为 `transcript → TopSeparator → composer → BottomSeparator → footer`,其中:

- `TopSeparator`/`BottomSeparator` 用细线 widget(Textual `HorizontalRule` 或 1 行高 Static),低对比色(BORDER_MUTED);
- composer 为 `Horizontal` 容器,固定 `height: 1`:`❯`(Label,accent)+ `Input`(Textual 自带无边框输入,聚焦态只换 prompt 颜色);
- 移除 `_InputBox` 的 round border 与自由高度,不再与输入状态抢注意力。

备选:保留大边框输入框只改高度——被否决,双重边框是截图里最刺眼的视觉噪音,与参考图的"连续命令行"不符。

### D2: 用户消息 = 命令记录行

`UserBlock.render` 改为 `❯ 文本`(无背景、无补齐 pad):`❯` 用 ACCENT,文本用 TEXT。去掉全宽 `USER_BG` 补齐逻辑。

备选:受限宽度气泡(72% 终端)被用户否决——参考图是命令记录而非气泡。

### D3: 思维链弱化(始终展开)

`AssistantBlock.render` 输出:

```
Thought for 3s · 1 tool call     ← DIM 元信息标题
│ 检查组件层…                      ← 每行:THINKING 灰 + "│ " 前缀 + 2 列缩进
```

- 元数据由 `TuiModel` 本地测量,不改 core:`TuiModel` 构造接收可注入 `clock: Callable[[], float]`(默认 `time.monotonic`),首个 THINKING_DELTA 记 `thinking_started`,首个 TEXT_DELTA 记 `thinking_ended`;TOOL_CALL 事件计数工具数。两端都有时间戳才显示耗时,否则只显示「思考」;工具数 >0 才显示 `· N tool calls`。clock 注入保持"给定事件序列 → 渲染行"纯函数可测(测试注入假时钟)。
- 竖线行渲染:`│ {text}`,fg=THINKING,左缩进 2 列。

### D4: 工具摘要 formatter(components.py 内私有函数)

不改工具 schema、不动 core 事件。`ToolCallBlock` 构造改为收结构化 `args: dict`,header 渲染:

```
▶ · read src/codeagent/app/tui/components.py     ← 折叠态
▼ ✓ bash uv run pytest -q · exit 0 · 12.3s       ← 展开态(尾部附结果摘要)
```

- 折叠符:`▶`(折叠)/`▼`(展开),fg=DIM;状态图标 `·/✓/✗` 沿用;
- `_summarize_args(name, args) -> str`:read/write/ls → `file_path`;edit → `file_path`;bash → `command`(截断 ~60 字符);grep → `pattern in path`;find → `pattern`;未知 → 原 JSON;
- `_summarize_result(name, result) -> str | None`:bash 解析 `退出码: N(耗时 Xs)` → `exit N · Xs`;write 解析 `已写入 …(N 字节)` → `N B`;edit 解析 `已替换 N 处` → `N 处`;其余取结果首行截断;解析失败回退首行,不破坏折叠态;
- 摘要一律 DIM 展示在 header 尾部;展开时仍显示完整结果(TOOL_OUTPUT)。

### D5: Footer 双端布局 + 富样式契约

- 新增 `FooterLine` 组件(components.py):数据 `status_text`(左端状态)+ `keys`(左端快捷键)+ `model` + `effort`;render 双端:左侧 `● ready · Esc 退出`,右侧 `model · effort`(右对齐,宽度不足截断右侧优先);
- `backend.py` 契约:`set_status(text: str)` → `set_status(line: RichLine)`;新增 `set_footer(line: RichLine)`;`view._flush_render` 直接传 `status.render(width)[0]` 与 `footer.render(width)[0]`;
- `model/effort` 数据来源:组合根新增 `container.create_tui_app()` 工厂(唯一跨层点,与规范一致),内部 `Settings()` + `ai.model_pattern.split_model_pattern`(唯一解析实现)得到 `(model, effort)`,构造 `TuiApp(session, backend, footer=FooterInfo(...))`;`TuiApp` 构造 `footer` 参数带默认值,`tests/tui/test_view.py` 的 StubBackend 无需改构造,仅改 `set_status` 签名。

### D6: theme 标签复用

尽量复用现有标签:折叠符/摘要/元信息 → `DIM`,竖线 → `THINKING`,用户 `❯` → `ACCENT`。预计零新增标签;如实现中确需,再按「受控词表」模式追加。

## Risks / Trade-offs

- [单行 composer 无法容纳超长输入/多行粘贴] → Textual `Input` 支持横向滚动,MVP 接受(参考图同为单行);多行输入下一轮随编辑器增强处理。
- [摘要 formatter 依赖工具结果文本格式,工具输出格式演进会失效] → 解析失败一律回退首行摘要,折叠态永不崩溃;formatter 集中在 components.py 单点维护。
- [footer 的 model/effort 在 TuiApp 构造时固化,运行中改配置不更新] → MVP 接受;effort 切换(H8)是后续会话管理功能,不在本轮。
- [契约升级 `set_status` 影响 StubBackend 与现有测试] → 同步更新 `tests/tui/test_view.py` 的 stub 与断言,保持全量测试通过。
- [思维链耗时依赖 clock 注入,真实会话中事件间间隔即思考耗时] → 语义正确(首次正文 token 到达即思考结束);离线测试用假时钟,无时序依赖。

## Migration Plan

纯前端样式重构,无数据迁移、无外部依赖变更;`--tui` 入口行为不变,headless 不受影响。回滚 = 还原 git。

## Open Questions

(无——本轮范围已由用户确认:布局+样式,Markdown/滚动/点击留待下一轮。)
