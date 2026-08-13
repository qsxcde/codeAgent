## Context

动机与范围见 `proposal.md`。现状要点:

- 当前仅 headless(`app/main.py` 聚合事件);TUI 在 2026-08-13 重构中移除,FR-1.11 登记 v0.2 恢复;
- 会话层事件设施已就绪:`AgentSession.run()`(全异步)/ `abort()` / `subscribe()`,`EventBus` 同步扇出 10 类 `AgentEvent`;headless 的事件聚合语义(text_delta 累积 → tool_call 前清零 → agent_message 去重)可复用;
- `core/`、`session/`、`tools/`、`ai/` 对 TUI 是黑盒;TUI 属 `app/` 层(唯一允许跨层 import);
- 测试哲学:离线可测最高原则(NFR-M2)、断言行为不实现、`FakeClient.steps` 脚本化事件流、断言平台无关。

设计参照:Pi-Agent(`earendil-works/pi`)TUI 逻辑——长命组件树 = 状态 + 渲染驱动式差分(`requestRender` 合并)+ 事件驱动更新 + 视口 follow-end 滚动 + alt 屏专用 + 引擎可换(共享 `TUI` 接口,`TuiMainScreen`/`TuiAltScreen`)。

## Goals / Non-Goals

**Goals:**
- MVP 交互式终端:对话输入/流式回复渲染、运行中打断、状态栏实时反馈、alt 屏渲染、退出打印完整文档(FR-1.1/1.2/1.7、FR-6.3、NFR-P5/U2/U4);
- 组件树与引擎解耦:组件是纯 `render(width) -> list[str]`,引擎无关、离线可测;
- `TuiBackend` 端口 + textual 实现(引擎 1),为将来自研引擎留缝;
- 事件驱动 + `requestRender` 合并,流式 ≥30fps。

**Non-Goals:**
- 斜杠命令体系 / 模糊补全 / 命令选择器(provider/model/effort)/ `//` 转义 / Tab 补全 / Ctrl+L 聚焦(FR-1.3~1.6/1.8,拆下一迭代,`Editor` 留扩展缝);
- main screen 模式(只做 alt 屏);
- 自研渲染引擎(本次只用 textual 实现端口);
- 会话持久化 / 上下文压缩 / 会话分叉(仍属 v0.2 其它项);
- `core/`、`session/`、`tools/`、`ai/` 任何改动。

## Decisions

### D1. TuiBackend 端口 + textual 实现(引擎可换)

```python
class TuiBackend(Protocol):
    def run(self) -> None: ...                 # 进入 alt 屏并启动事件循环
    def render(self, lines: list[str]) -> None: ...   # 差分更新 transcript 区
    def set_status(self, text: str) -> None: ...
    def on_submit(self, handler) -> None: ...  # 编辑器提交(发送消息)
    def on_interrupt(self, handler) -> None: ...   # 运行中中断 / 空闲退出
    def on_resize(self, handler) -> None: ...
    def exit_document(self, lines: list[str]) -> None: ...  # 退出打印完整文档
```

- **为什么端口**:组件/逻辑与引擎解耦——textual 只是把行画到 alt 屏 + 收输入;将来自研引擎实现同一接口即可,`view.py` 与组件零改动;
- **备选**:直接 textual widget 树(快但引擎耦合死)、自研引擎(工程量巨大);
- 依赖加 `textual`(主依赖,运行时入口需要)。

### D2. 组件 = 纯 render(width) 对象(pi 双树)

`app/tui/components.py` 定义长命组件树;每个组件实现 `render(width) -> list[str]`,不碰终端、不碰 textual:

```
Transcript  (有序子块列表 + 滚动状态)
├─ UserBlock(prompt)
├─ AssistantBlock(thinking 折叠区 + body 文本)
├─ ToolCallBlock(name, args, status: pending→done/error, result)
├─ ErrorBlock(text) / CancelledBlock()
StatusLine(status, model, usage)          # 状态栏
Editor(输入状态)                          # MVP 只暴露文本 + 提交;补全/命令缝留到下一迭代
```

- **为什么纯 render**:组件渲染是纯函数 → 注入 `FakeClient.steps` 脚本事件序列即可离线断言渲染行,零终端依赖(对应 spec「组件渲染离线可测」);
- 渲染调度只重建**帧**(把组件树画成行),组件状态缓存长命(pi 第 2 条:长命组件树 vs 每帧快照)。

### D3. 事件 → 组件映射(核心)

`view.py` 的 `TuiApp` 订阅 `AgentSession`,把事件翻译成组件状态变更:

| AgentEvent | 组件状态变更 |
|---|---|
| `session_started` | Transcript 追加 UserBlock(prompt) |
| `thinking_delta` | AssistantBlock.thinking 累积 |
| `text_delta` | AssistantBlock.body 累积 |
| `agent_message` | 定稿该块(去掉"…"占位) |
| `tool_call` | 追加 ToolCallBlock(name+args),状态 pending |
| `tool_result` | 该块状态 → done/error,展示截断结果 |
| `turn_end` | 标记本轮完成 |
| `error` | ErrorBlock + 状态栏 ERROR |
| `run_cancelled` | CancelledBlock + 状态栏 IDLE |
| `usage` | 状态栏用量 |

事件回调**只改状态,不直接渲染**;改完调 `request_render()` 排入下一帧。

### D4. 渲染合并与 30fps

- `request_render()` 合并:同一帧内到达的所有事件增量合并成一次 layout + 渲染(pi 的 render-driven);
- textual 后端在每帧把 transcript 行 `render()` 到 widget,textual 做屏幕差分;
- 事件回调里不做任何渲染/IO,避免阻塞;
- ≥30fps 靠「合并 + 差分」而非「每 token 重画」。

### D5. 打断与退出语义(统一 Esc)

- **运行中 `Esc`** → `session.abort()` → `run()` 广播 `RUN_CANCELLED` → 组件加 CancelledBlock + 状态栏回 IDLE → 输入框可用;
- **空闲 `Esc`** → 退出:先 `exit_document()` 以无界宽度打印完整 transcript,再退出 alt 屏(pi 第 6 条:退出文档 = 逻辑完整,非最后一屏截屏);
- 键事件由 textual 捕获转发,不走 SIGINT——避免与 asyncio 事件循环 / 终端信号冲突(Esc 是纯应用层键,无终端信号副作用)。

### D6. Editor 扩展缝(下一迭代)

`Editor` 组件只暴露「文本 + 提交 + 光标」;补全提供者与命令解析器是**可插接口**(本次不实现):
`Editor` 预留 `set_completion_provider(...)` / `set_command_handler(...)`;斜杠命令、模糊补全、选择器下一迭代注入,组件/后端不动。

### D7. textual 后端承接方式

textual 后端用一个「显示行」的 widget 呈现组件渲染出的 ANSI 行(而非映射成 textual 原生 widget 树),Editor 用 textual `Input`:

- **为什么**:保持组件纯 `render(width)`,端口语义干净;textual 只负责 alt 屏 + 差分 + 键事件 + 编辑器原语;
- **代价**:textual 的布局/主题能力用得浅(transcript 是行集合而非结构化 widget);MVP 足够;
- 若后续需要富交互(行内按钮、聚焦的块级导航),再评估迁移到 textual 原生 widget 树。

### D8. 布局与滚动条语义

- **Dock 固定 + Transcript 独立滚动**(pi 布局):`Transcript`(flexible,可滚动视口)在上,`Dock`(固定,StatusLine + Editor + Footer)在底——**Editor 永远钉在终端底部,与滚动位置无关**,消息在 Transcript 区域内独立滚动;
- **MVP 不画可见滚动条(纯视口)**:alt 屏下终端无原生滚动条,若要有需自绘(组件渲染加一列);MVP 选择纯视口——视口偏移 + follow-end 跟底 + 滚轮/键盘滚动即是全部滚动体验,少画一样东西;滚动条留作下迭代可选增强(只需 Transcript 渲染加一列,不破坏接口);
- 小终端优先级(pi):先保 Transcript 至少一行,再保 Editor 光标可见,最后 Footer。

## Risks / Trade-offs

- **[textual 是重依赖,曾被移除]** → 恢复项(FR-1.11)明确接受;`TuiBackend` 端口保证引擎可换,不会二次锁死;
- **[组件纯 render 与 textual 集成度有限]** → MVP 场景(行渲染)够用;富交互按 D7 备注再评估;
- **[30fps 依赖渲染合并正确]** → 事件回调零渲染、`request_render` 合并;测试断言「N 个增量 → 1 次渲染」;
- **[Esc 双义(中断 vs 退出)]** → 以运行态判定:运行中中断、空闲退出,状态栏与测试覆盖两态;
- **[多轮上下文验证依赖会话]** → 用 `FakeClient.steps` 脚本多轮事件,断言组件树/渲染行,不依赖真实模型。

## Migration Plan

- 新增 `src/codeagent/app/tui/` + `tests/tui/`,pyproject 加 `textual`;现有 headless 与事件语义零改动;
- 入口:`uv run codeagent --tui`(在 `app/main.py` 加 flag,headless 保持默认);
- 门槛:全量 `uv run pytest` 绿(现 224 + 新增);MVP 人工验收:可对话/可流式/可打断/状态栏正确/退出打印完整文档;
- 回滚:`git revert`,移除依赖即可,无跨层耦合。

## Open Questions

无(组件纯度、后端接法、Ctrl+C 语义、入口形态均已在上方定为决策或记录性假设,不改变 spec 或任务拆解)。
