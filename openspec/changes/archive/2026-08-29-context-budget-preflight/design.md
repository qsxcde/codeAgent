## Context

`context-budget-contract` 已提供 `ContextBudgetSnapshot`，并在模型请求准备阶段发布估算事件；当前 ReAct 循环仍会直接把最终上下文交给模型，没有统一的“是否允许发送”判定。现有会话收尾已经能区分失败、取消和成功提交，因此本变更只需要在模型调用边界增加一个纯预算决策，并把结果接入已有运行失败与 usage 提交流程。

实现必须继续遵守分层约束：预算判定和稳定错误类型放在 `core`，模型/工具/配置细节留在组合根，session 只维护运行状态和提交边界，自动压缩与工具结果治理不在本变更内完成。

## Goals / Non-Goals

**Goals:**

- 对每个实际模型请求使用最终临时上下文执行一次可复现的预算判定。
- 用稳定的判定状态、阈值配置、事件字段和错误码表达安全、临界、超限及不确定情况。
- 在 provider 调用之前阻断确定性超预算和策略要求阻断的不确定请求。
- 保持预算阻断与现有 session 回滚、usage 提交、取消和唯一终态契约一致。
- 为后续自动压缩、工具结果治理和 TUI 展示提供不改变主循环职责的消费接口。

**Non-Goals:**

- 不在本变更中自动压缩上下文、截断或摘要工具结果。
- 不实现 provider 专属 tokenizer、网络重试或新的 provider 协议。
- 不把预算 warning 直接渲染到 TUI/CLI；本变更只发布结构化事件。
- 不修改 JSONL 消息、usage、压缩记录和父级链格式。

## Decisions

### 1. 在模型调用边界执行前置判定

预算判定放在上下文扩展完成后、选择 `stream`/`generate` 之前，复用该次最终 `ContextBudgetSnapshot`。这样系统判断的是实际将发送给模型的临时视图；工具调用后的下一次请求会自然重新计算，不会复用旧结果。

备选方案是在 session 层按历史长度提前判断，但 session 不掌握 system prompt、工具 schema 和扩展后的临时消息，容易与真实 provider 请求不一致，因此不采用。

### 2. 采用四态结果和显式阻断原因

core 增加 provider 无关的前置判定结果，状态固定为 `safe`、`near_limit`、`over_limit` 或 `uncertain`，同时携带快照、`allowed`、原因和阈值信息。判定优先级为：

1. 预算来源为 `uncertain` 时先按 `uncertain_budget_policy` 决定；`allow` 继续但保留 `uncertain`，`fail` 阻断；
2. 可确认预算且 `headroom < 0` 时判定为 `over_limit` 并阻断；
3. 余量达到警戒线时判定为 `near_limit` 并继续；
4. 其它情况判定为 `safe` 并继续。

这样不会把 fallback 估算伪装为精确容量，也不会因为不确定状态被错误地包装成 provider 错误。`over_limit` 与 `uncertain + fail` 使用不同原因，方便后续压缩策略区分。

### 3. 阈值使用互斥的 token/比例配置

在 core 配置中提供 `warning_headroom_tokens` 与 `warning_headroom_ratio` 两种表达方式，二者最多启用一个；默认使用固定 token 阈值，保证小窗口模型不会因比例计算出现歧义。token 阈值必须为非负整数，比例必须为 `(0, 1]`，未启用阈值时只判定是否超预算。

备选方案是同时启用两个阈值并取更严格值。该方式虽然保守，但会使不同配置下的 warning 边界难以解释，因此先采用互斥配置，后续如有数据再扩展。

### 4. 通过结构化事件和专用错误连接 session

每次判定发布 `context_preflight` 事件；其 payload 使用中立结果对象，不让订阅方解析文本。阻断时抛出带稳定错误码、phase、判定状态和预算字段的本地错误，session/runtime 将其归类为不可重试的上下文准备失败。模型请求未开始，因此不会产生工具副作用或 provider usage。

session 在运行期保存最近一次 preflight 结果，但不把 warning 或 estimate 写入 JSONL；只有已有成功提交路径才能聚合 provider usage。

### 5. 只阻断，不在本变更中恢复

超预算后只返回可操作诊断并结束本轮。自动压缩、工具结果截断和用户引导属于不同策略，需要消费相同的结构化结果并拥有各自的回滚/可见性规则，直接塞入本变更会重新耦合主循环，因此留给 V4-13、V4-14 和 V4-16。

## Risks / Trade-offs

- **[本地估算与 provider tokenizer 不一致]** → 只对 `estimate` 且明确超限的请求强阻断；窗口不确定时按显式策略处理，并在事件中保留来源。
- **[warning 阈值过于敏感]** → warning 不阻断、不重试，阈值可配置，并通过结构化事件交给后续 UI/策略层调整。
- **[扩展前后预算不一致]** → preflight 只消费最终临时视图的快照，扩展每次请求重新运行，避免使用初始历史预算。
- **[新增事件影响旧订阅方]** → 使用新增事件类型和向后兼容的结构化 payload，旧订阅方可忽略未知过程事件；更新精确事件序列测试。
- **[阻断与 session 收尾交错]** → 复用既有 RuntimeFailure、rollback 和 commit gate，不新增独立的失败生命周期。

## Migration Plan

1. 在 core 增加判定结果、阈值配置和本地预算错误，并为四种结果建立纯函数测试。
2. 在模型请求前接入最终快照判定和 `context_preflight` 事件，确保阻断发生在 provider 调用之前。
3. 在 session/runtime 接入最近判定状态、错误分类和失败轮次隔离；不改变 JSONL 格式。
4. 在 app/composition 为现有配置提供默认阈值和 `uncertain_budget_policy` 透传，并补齐跨层装配测试。
5. 运行相关窄测试、边界导入检查和 OpenSpec 校验；完整测试由交付阶段单独执行。

回滚时移除请求前判定装配即可恢复“只记录预算快照”的行为；保留 `ContextBudgetSnapshot`、usage 和既有持久化格式，不需要数据迁移。
