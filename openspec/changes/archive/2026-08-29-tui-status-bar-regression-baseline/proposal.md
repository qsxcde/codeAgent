## Why

V4-19 的状态栏三栏布局已经能够固定区域边界，但验证阶段的耗时仍复用 Agent runtime 时间，且在没有新事件时不会持续刷新。现在需要把这项已有能力纳入稳定回归基线，避免状态栏显示停滞、计时语义错误或窄终端布局回退。

## What Changes

- 为任务验证与修复阶段提供独立、可持续更新的阶段耗时；进入终态后冻结计时并停止刷新任务。
- 在 runtime 或任务状态处于活动阶段时，以低频、非阻塞方式刷新状态栏，即使没有新的 Agent 事件也能更新耗时。
- 保持会话信息区、运行状态区和上下文信息区的固定槽位；补齐所有任务终态、宽度断点、长命令、中文混合文本和上下文位数变化的回归断言。
- 验证状态栏计时任务不会影响输入、取消、滚动、确认和现有渲染调度，也不改变 `TuiBackend.set_status()` 契约。
- 更新 V4-19 迭代文档，将“已有基础”细化为可验证的回归基线状态。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tui`: 明确状态栏动态耗时的来源、刷新和终态语义，并补齐固定槽位的回归覆盖。

## Impact

- 影响 `src/codeagent/app/tui/presentation/status.py`、TUI 状态模型和渲染协调器的状态投影与刷新调度。
- 增加 TUI 状态栏单元/契约测试，必要时增加基于 `TuiRenderCoordinator` 的异步集成测试。
- 更新 `docs/iteration/v0.4.md` 和 `openspec/specs/tui/spec.md` 对应契约。
- 不修改 `core`、`session`、`ai`、`tools`，不新增依赖，不改变事件和后端公开接口。
