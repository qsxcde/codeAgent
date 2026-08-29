## Context

当前 Agent 已通过 `Agent.subscribe` 发布结构化 core 事件，Session 通过 EventBus 发布带 `session_id` 的适配事件；两者缺少统一的生命周期域和阶段契约。模型请求边界已有事件常量但没有实际发布，session 侧也没有独立的观察 Hook 入口。实现必须继续遵守 core 不依赖 session、provider、tools 或 app 的边界。

## Goals / Non-Goals

**Goals:**

- 在 core contracts 中定义不可依赖具体基础设施的 Hook 事件和回调类型。
- 复用现有 Agent 异步监听收尾语义，使 core Hook 按顺序观察、且不接管运行决策。
- 在 session 事件适配边界补充 session scope，并为模型请求发布明确开始/结束事件。
- 通过配置注入而非全局注册，使 Agent、SessionManager 和组合根可以独立测试。

**Non-Goals:**

- 不在本变更中定义 Hook 异常诊断、熔断、重试或超时策略；这些属于 V4-29。
- 不允许观察 Hook 修改上下文、工具结果或安全决策；受控 Transformer 属于 V4-30。
- 不实现插件发现、第三方代码执行、审计存储或遥测后端。

## Decisions

### 1. 使用统一的结构化快照，而不是让扩展直接解析原始字符串

新增 `LifecycleHookEvent`，以 `scope`/`phase` 加上原始 `AgentEvent` 快照表达生命周期。快照会复制 metadata，避免 Hook 修改共享事件；原始事件仍按兼容路径继续发送给已有订阅方。

选择该方案是因为已有事件类型和工具关联字段已经稳定，包装它们可以避免重复定义 payload；相比向 Hook 暴露裸 `AgentEvent`，显式域和阶段能让扩展不必维护事件类型映射。

### 2. core 与 session 使用同一 Hook 类型、分层产生事件

Agent 只为 turn、model、tool 产生 core scope；SessionEventMixin 只为 session scope 产生观察事件，并从已经补充关联信息的 session 事件构造快照。这样 core 不引入 session 生命周期，且一个 Hook 在 AgentSession 中可同时观察四个 scope，不会因为同一事件跨层转发而重复收到 core scope。

### 3. Hook 复用 Agent 的监听队列

`AgentLoopConfig` 持有有序 Hook 集合，Agent 将每个 Hook 包装成现有事件监听器，因此同步 Hook 的调用顺序、异步 Hook 的等待和取消收尾沿用已有实现。Session scope 在同步 EventBus 发布点调用相同的 Hook 入口；本变更的公共契约以同步观察为主，后续若需要 session 异步 Hook 可在异常隔离变更中统一扩展。

### 4. 模型请求以显式边界事件表示

模型请求开始时发布 `MODEL_REQUEST_STARTED`，在成功、异常或取消路径发布一次 `MODEL_REQUEST_FINISHED`，状态和错误信息放入 metadata。流式消息、预算、前置判定和用量作为 model updated。显式边界比把 `MESSAGE_START/END` 隐式解释为模型请求更稳定，也保留消息事件原有含义。

## Risks / Trade-offs

- [Hook 快照复制增加少量开销] → 只复制结构化事件及其 payload 的必要快照，不改变原始事件传递；以行为测试确认工具和消息对象不被 Hook 变更。
- [session 同步 Hook 可能执行较慢] → 只读 Hook 不参与控制决策，先保持现有同步 EventBus 语义；异步调度、异常隔离和诊断在后续 Hook 稳定性变更中统一处理。
- [模型失败时边界事件容易遗漏] → 使用请求级 `try/finally`，测试正常、失败和取消三条路径各只产生一个 finished。

## Migration Plan

1. 增加 core Hook 类型、配置字段、生命周期映射和模型请求边界事件。
2. 在 session 适配层接入 session scope，并在组合根暴露注入参数。
3. 运行 Hook、取消、工具和导入边界回归测试，更新文档和 v0.4 状态。
4. 失败时移除配置注入和映射调用即可回退到现有 EventBus/Agent.subscribe 行为；原有事件类型不删除。
