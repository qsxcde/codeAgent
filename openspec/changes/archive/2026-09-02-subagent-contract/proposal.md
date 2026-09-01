## Why

v0.4 的 Agent Runtime 只能稳定表达单个 Agent 的运行生命周期，父 Agent 还没有一个与模型、Session、工具实现解耦的 Subagent 委派协议。若直接复用 `session` 的 `RunPhase` 或把子运行伪装成普通 `ToolResult`，会混淆执行阶段、持久化收尾和父子运行关系，导致取消、超时、预算耗尽及失败结果无法被一致处理。

现在先固定 provider-neutral 的核心契约和独立的委派状态模型，可以为后续串行运行器、上下文隔离、取消治理和 TUI 观测提供稳定边界。

## What Changes

- 在 `core` 中新增 `SubagentRequest`、`SubagentResult`、`SubagentStatus`、预算值对象和结构化失败信息。
- 新增独立于 `session.RunPhase` 的 Subagent 委派状态机，约束排队、启动、运行、确认、取消和终态转换。
- 新增 `SubagentRunner` provider-neutral 端口，规定执行、取消和事件回调的最小调用面。
- 为核心事件增加父子运行关联字段，包括 `delegation_id`、`parent_run_id`、`child_run_id`、`attempt_id` 和 `depth`。
- 统一请求校验、权限拒绝、深度超限、预算耗尽、超时、父级取消和执行失败的状态与 `reason_code` 映射。
- 增加核心契约、状态机、终态唯一性、公共导出和依赖边界测试。
- 本变更不接入真实 `AgentSession`、模型、工具、持久化或 TUI；这些属于后续运行时和观测变更。

## Capabilities

### New Capabilities

- `subagent-contract`: 定义父 Agent 委派子 Agent 时使用的 provider-neutral 请求、结果、状态机、运行器端口和父子事件关联契约。

### Modified Capabilities

无。现有单 Agent ReAct、Session 生命周期和工具执行需求保持不变。

## Impact

- 影响 `src/codeagent/core/contracts/` 的公共类型、错误契约和事件形态，并同步 `codeagent.core` 公共门面导出。
- 增加 `tests/core/` 契约和状态机测试，更新 core 包结构测试。
- 不新增第三方依赖；core 继续只依赖标准库和本包内部模块，不导入 `ai`、`tools`、`session` 或应用配置。
- 后续 `app/composition/subagent/` 可以实现运行器，但本变更不会改变现有父 Agent 的执行路径。
