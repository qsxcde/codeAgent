## Why

`view.py` 和 `components.py` 分别集中了承担输入、命令、会话、任务、恢复、渲染、组件和状态投影等多种职责，修改局部功能需要理解过大的状态面。现在应在保持 TUI 行为不变的前提下，建立清晰的职责边界，为后续性能优化降低风险。

## What Changes

- 将 `TuiApp` 收敛为装配和生命周期外观，抽离交互、会话、对话任务、恢复和渲染协调职责。
- 将 `components.py` 拆分为渲染基础类型、消息块、Transcript、状态栏和 TUI 状态投影等内聚模块。
- 消除 Markdown 渲染器与组件模块之间的循环依赖，建立单向依赖的富文本基础类型。
- 保持 `TuiBackend` 协议与 Textual 引擎隔离，继续限制具体终端引擎依赖的出现位置。
- 迁移并补齐离线行为测试与导入边界测试，确保命令、滚动、会话恢复、确认和退出语义不变。

## Capabilities

### New Capabilities

无。该变更是内部职责重构，不增加用户可见功能。

### Modified Capabilities

无。既有 TUI 契约保持不变。

## Impact

- `src/codeagent/app/tui/view.py`、`components.py` 及新增的同层职责模块。
- `src/codeagent/app/tui/backend.py`、`textual_backend.py`、`md_renderer.py` 的导入边界。
- `src/codeagent/app/composition/tui_factory.py` 的装配方式。
- `tests/tui/` 和 `tests/test_decoupling.py`。
