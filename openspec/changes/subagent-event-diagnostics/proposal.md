## Why

V5-05 已能把子 Agent 的结构化结果交给父 Agent，但运行中的子事件目前仍被塞进父级 `tool_progress` 的嵌套 payload，消费者无法直接识别委派、子运行或当前阶段。真实运行中还缺少统一的委派状态提交点，完成、取消、超时和迟到事件可能产生重复或相互覆盖的终态诊断。

现在补齐父子事件关联和运行诊断，可以让后续 TUI/CLI 在不读取子 transcript 的前提下展示可靠的委派进度，并为取消、失败和清理不确定保留可追踪事实。

## What Changes

- 增加面向父级事件流的 Subagent 事件 envelope，区分排队、启动、进度和终态事件；事件保留 `delegation_id`、父子 run、`attempt_id`、深度、父级序列和子级序列。
- 将子 Agent 的有限生命周期/工具阶段摘要提升为父级事件总线可直接消费的顶层事件，不再把完整子事件对象或无界 transcript 作为 `tool_progress` payload 转发。
- 将 `SubagentState` 接入真实串行 runner，统一记录状态转换、终态结果和终态事件发布；同一 delegation 只发布一次终态，重复完成、取消和迟到子事件只保留有限诊断。
- 覆盖排队取消、启动失败、正常完成、预算耗尽、墙钟超时、父级取消、子事件回调失败和清理不确定等诊断路径，保持稳定 reason code 与现有 ToolResult 映射。
- 保持旧单 Agent 事件、`tool_progress` 回调和无 Subagent runner 的装配行为兼容；本变更不负责 TUI 组件展示、JSONL 持久化或并行调度。

## Capabilities

### New Capabilities

无。本变更扩展既有 Subagent 契约和运行时能力。

### Modified Capabilities

- `subagent-contract`：明确父级事件 envelope、父子序列、子事件负载边界和委派终态唯一性。
- `subagent-runtime`：增加运行器发布父子事件、状态诊断和迟到事件处理要求。

## Impact

- 影响 `core/contracts/events.py`、`core/contracts/subagent_state.py`、`core/contracts` 公共导出以及 `app/composition/subagent/` runner/事件辅助模块。
- 影响核心工具调用的事件转发边界，使结构化 Subagent 事件可以绕过通用工具进度的嵌套包装并进入父级 Session EventBus。
- 增加 core 契约测试、runner 单元测试和 FakeClient/Session 集成回归；不新增运行时依赖，不改变模型 provider、持久化格式或普通 TUI transcript。
