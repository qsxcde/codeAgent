## Why

`context-budget-contract` 已经能在请求前计算输入组成和剩余空间，但当前预算快照主要用于记录，尚未阻止明显超预算的请求。长会话、大工具结果或切换到小窗口模型时，系统仍可能把必然失败的请求发送给 provider，造成额外延迟、模糊错误和不必要的重试。

现在需要把预算从“诊断数据”推进为模型请求前的可靠性门禁，同时保留不确定窗口的可解释行为，并为后续自动压缩和工具结果治理提供稳定的决策输入。

## What Changes

- 在模型请求前增加统一的预算检查，区分安全、接近阈值、超出输入预算和预算不确定等结果。
- 为接近阈值和超预算定义可配置的阈值、结构化诊断字段与稳定错误码，避免依赖 provider 返回窗口错误。
- 超预算请求在调用模型前由 runtime 阻断，并保持本轮消息、usage 和持久化事务不变。
- 为预算不确定的旧模型适配器沿用 `allow` / `fail` 显式策略，不把 fallback 估算伪装成精确容量。
- 允许组合根注入后续处理决策，但本变更不实现自动压缩、工具结果截断、MCP/Skill 编排或 TUI 展示。
- 增加小窗口、临界值、超预算、失败回滚、取消和多轮 ReAct 的离线契约测试。

## Capabilities

### New Capabilities

- `context-budget-preflight`: 定义模型请求前预算检查、阈值判定、结构化诊断和阻断语义。

### Modified Capabilities

- `core`: 模型请求前增加预算门禁及稳定的过程/错误事件语义。
- `sessions`: 会话在预算阻断时保持本轮回滚、累计 usage 和持久化边界不变，并暴露最近一次预算诊断。

## Impact

- 影响 `src/codeagent/core/` 的预算检查、请求循环、错误和事件契约。
- 影响 `src/codeagent/session/` 的运行收尾、失败分类和预算诊断状态。
- 影响 `src/codeagent/app/composition/` 的阈值和策略装配，但不改变 provider 协议。
- 新增 core/session/app 的离线回归测试；不需要真实 API key、网络或 provider tokenizer。
- 不改变 JSONL 消息、usage、压缩和父级链格式；自动压缩与工具结果治理留给后续变更。
