## Why

项目当前只有 headless CLI(`app/main.py`);交互式终端形态(TUI)在 2026-08-13 重构中整体移除,恢复需求登记为 FR-1.11(P1)。恢复的底座已就绪——会话层事件接口(`AgentSession.subscribe()` / `run()` / `abort()`,10 类 `AgentEvent` 经 `EventBus` 分发)与 headless 的事件聚合语义可直接复用,缺的只是把事件流渲染成交互终端。按 Pi-Agent(`earendil-works/pi`)的 TUI 设计逻辑恢复:长命组件树 = 状态、渲染驱动式差分、事件驱动更新、alt 屏专用、引擎可换。

## What Changes

- **新增 `app/tui/` 交互式终端**(MVP 先行):对话(输入/发送/流式回复)、运行中打断(`Ctrl+C` → `session.abort()` → `RUN_CANCELLED`)、状态栏(`RUNNING / IDLE / ERROR` + 模型 + token 用量)、alt 屏专用、退出时打印完整对话文档;
- **组件树与引擎解耦**(pi 架构):`components.py` 是长命组件树,纯对象 `render(width) -> list[str]`,引擎无关;`backend.py` 定义 `TuiBackend` 端口(start/stop/set_lines/on_key/on_resize);`textual_backend.py` 用 textual 实现差分渲染 + alt 屏 + 输入(引擎 1,为将来自研引擎留缝);
- **`view.py`(TuiApp)**:订阅 `AgentSession` 事件 → 更新组件状态 → `request_render()` 合并 → 每帧一次差分渲染(≥30fps,NFR-P5);事件回调只改状态、不直接渲染;
- **事件 → 视图映射**:`text_delta`/`thinking_delta` 流式累积到 AssistantBlock,`tool_call` 追加 ToolCallBlock,`tool_result` 更新其状态,`usage` 更新状态栏,`error`/`run_cancelled` 进块 + 状态栏;
- **新增依赖**:`textual`(渲染后端;恢复被移除的依赖);
- **拆到下一迭代(不在本次)**:斜杠命令体系(`/help /clear /model …`)、模糊补全、命令选择器(provider/model/effort)、`//` 转义、Tab 路径补全、`Ctrl+L` 聚焦等 FR-1.3~1.8 导航能力;`Editor` 组件接口留扩展缝(补全提供者/命令解析器可插);
- **BREAKING**:无(新增模块 + 新增依赖,现有 headless 形态与事件语义不变)。

## Capabilities

### New Capabilities

- `tui`:交互式终端形态能力——对话输入/流式回复渲染、运行中打断、状态栏实时反馈、alt 屏渲染、退出完整文档;覆盖 FR-1.1/1.2/1.7、FR-6.3、NFR-P5/U2/U4 的 MVP 子集。

### Modified Capabilities

无。

## Impact

- **新增代码**:`src/codeagent/app/tui/`(components / backend / textual_backend / view / main);`tests/tui/` 镜像;
- **依赖**:`pyproject.toml` 加 `textual`(dev 组或主依赖——入口运行时需要,归主依赖);
- **消费的既有设施**(零改动):`AgentSession.subscribe/run/abort`、`EventBus`、10 类 `AgentEvent`、`FakeClient.steps` 脚本化事件流(组件离线测试注入点);
- **不受影响**:`core/`、`session/`、`tools/`、`ai/` 与 headless `app/main.py` 全部零改动;
- **分层**:TUI 属 `app/` 层(唯一允许跨层 import),`app/main.py` 并列,可独立 import;
- **验收口径**:全量 `uv run pytest` 保持绿色(现 224 项 + 新增用例);组件树离线可测(注入 FakeClient 事件流断言渲染行);MVP 人工验收:可对话、可流式、可打断、状态栏正确、退出打印完整文档。

> 设计决策来源:Pi-Agent TUI 逻辑(渲染驱动差分 / 双树 / follow-end 视口 / 事件驱动 / alt 屏 / 引擎可换)+ 本仓库 FR-1.11 恢复需求。完整设计见 `design.md`。
