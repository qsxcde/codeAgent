## Context

参见 `proposal.md`。当前 `SessionRuntime` 以 `active_run_id`、`current_task` 和 `last_failure` 组合表达状态，`AgentSession.run()` 的执行、持久化和压缩收尾边界也不一致。本设计需要保持 core 的纯内存和依赖方向，同时让 session 成为一次完整运行的生命周期拥有者。

## Goals / Non-Goals

**Goals:**

- 让运行阶段和最终结果有单一来源，并能被 TUI、CLI、测试和后续扩展读取。
- 让错误分类、重试判断、副作用状态和清理确定性具有稳定字段。
- 让 core 事件与 session 事件各自保持职责，并能通过 run/session 标识关联。
- 让配置从组合根到实际 Agent 的透传完整且可测试。

**Non-Goals:**

- 不在 core 中引入 JSONL、SessionManager、TUI 或具体安全策略。
- 不在本变更中实现自动重试、上下文压缩策略或新的 provider。
- 不改变 ReAct 的模型—工具—模型基本循环。

## Decisions

### 1. 在 session/runtime 建立显式 RunState

由 session runtime 持有 `RunState`，包含 run/session 标识、当前阶段、取消请求、活动 operation、失败信息和收尾状态。阶段迁移通过受约束的方法完成，非法迁移在开发和测试中直接暴露。

选择 session/runtime 而不是 core 的原因是：core 只负责 Agent 内存执行，持久化、确认和资源关闭属于 session/application 生命周期。备选方案是在 `Agent` 中增加更多布尔字段，成本较低但会继续产生隐式状态，拒绝采用。

### 2. 用结构化 RuntimeFailure 替代字符串推断

错误对象至少包含 `code`、`message`、`phase`、`retryable`、`side_effect_state`、`cleanup_uncertain`、`operation_id` 和原始异常类型。中文提示只用于展示，策略和测试只读取稳定字段。

错误分类在边界处完成：core 报告执行事实，session 将模型、工具、确认、持久化和压缩异常映射为应用级错误码。

### 3. 统一终态发布顺序

一次运行采用“执行 → 判定 → 提交或回滚 → 资源收尾 → 发布终态 → 回到 idle”的顺序。`finish_run` 不再早于成功提交和自动压缩；提交或压缩失败必须进入同一失败收尾路径。

事件层保留 core 的过程事件，并由 session 发布一次完整运行终态。所有运行事件都携带 `run_id`，session 适配后补充 `session_id`；终态后丢弃或拒绝迟到事件。

### 4. 配置使用复制而不是手工重建

SessionRuntime 创建 Agent 时，从原始 `AgentLoopConfig` 复制所有执行相关字段，再覆盖 session 注入的 before hook、transform 和资源端口。这样保留 `tool_execution`、`after_tool_call` 和 `should_stop_after_turn` 的行为，避免字段新增时再次静默丢失。

## Risks / Trade-offs

- **[Risk]** 新增阶段和终态字段会改变 TUI/CLI 对运行状态的读取方式 → 保留既有事件名称和展示文本，在适配层提供兼容映射，并先增加契约测试。
- **[Risk]** 持久化失败被纳入运行失败后，调用方可能看到“模型已完成但运行失败” → 明确区分模型执行结果与会话提交结果，错误中标记 `phase=persistence`。
- **[Risk]** 迟到事件可能来自无法控制的异步监听器 → 为事件增加 run 生命周期校验，并逐步禁止未经等待的异步 listener。
- **[Risk]** 多个入口同时请求关闭或取消 → 终态迁移和收尾操作必须幂等，重复请求只返回已有状态。

## Migration Plan

1. 先增加状态、错误和事件契约模型及单元测试。
2. 将 `SessionRuntime` 和 `AgentSession.run()` 接入统一迁移与收尾路径。
3. 更新 TUI/CLI 状态读取和错误展示，保留现有公开 `abort()` 作为快速请求入口。
4. 通过 Runtime 契约测试后，再由后续变更实现等待式取消和资源收尾。

回滚时保留旧事件字段映射，撤回状态机接入即可；不迁移会话 JSONL 格式，不需要数据回滚。
