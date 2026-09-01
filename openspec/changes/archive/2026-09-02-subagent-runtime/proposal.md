## Why

v0.5 已经具备 provider-neutral 的 Subagent 契约，但父 Agent 仍没有可调用的真实委派入口。当前若把子任务直接追加到父会话，会污染上下文、复用错误的会话切换语义，也无法让父 Agent 得到可区分的子运行结果；现在需要先交付一个串行、只读、最大深度为 1 的最小闭环。

## What Changes

- 在应用组合层增加 `delegate` AgentTool，将模型工具调用转换为带父运行标识的 `SubagentRequest`。
- 增加串行 Subagent runner 和子运行工厂：一次只执行一个子任务，并为每次委派创建独立的临时 `AgentSession`、上下文、事件总线和运行资源。
- 让子 Agent 默认只接收 `read_only` 能力，不注入 `delegate`，从装配层阻止递归扩散和写入型副作用。
- 将子 Agent 的成功摘要或结构化失败结果转换成父 Agent 可继续推理的 `ToolResult`；父会话只接收委派结果，不追加子 Agent 的完整消息历史。
- 保留稳定的 `delegation_id`、父/子 `run_id` 和子运行终态，支持按委派标识取消活动子运行并在结束后释放子资源。
- 更新 Skill Adapter 的能力映射，让 Bootstrap 不再把已启用的 Subagent 能力报告为不可用。
- 增加 FakeClient 驱动的单元、契约和跨层集成测试，覆盖成功、串行排队、子运行失败、递归拒绝、上下文隔离和资源清理。

## Capabilities

### New Capabilities

- `subagent-runtime`: 提供父 Agent 的 `delegate` 入口、串行子运行隔离、结果回传和基础生命周期清理。

### Modified Capabilities

无。现有 `subagent-contract` 已定义本变更使用的请求、状态、结果、取消和事件关联契约，本变更只提供应用层实现。

## Impact

- 影响 `app/composition/` 的运行时和 Session 组合根、`session/` 的运行 ID 暴露/每次执行工具绑定、Skill Adapter 能力提示，以及 `tests/` 的跨层装配测试。
- 不新增第三方依赖；子 Agent 使用现有 Agent、AgentSession、模型、工具适配器、策略和资源关闭流程。
- `create_agent_config` 增加可选的 Subagent runner 装配能力；未启用 runner 的直接调用保持现有工具集合和行为。
- 子会话默认不持久化，父会话的 JSONL 格式不在本变更中扩展；结构化证据、完整预算治理、父子事件展示和运行记录留给后续 v0.5 变更。
