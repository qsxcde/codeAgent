## Why

当前 `core` 已经能够执行基本的 ReAct 循环，但消息模型、模型协议、会话持久化关系、安全确认、上下文压缩和工具实现细节仍集中在同一组端口与循环中。参考 Pi-agent 的 `agent-core` / `coding-agent` 分层，需要把 core 收敛为可复用的纯内存 Agent Runtime，使 Memory、MCP、Skill、Session 和安全策略通过扩展点或上层适配接入，而不是耦合进主循环。

## What Changes

- **BREAKING** 将 core 的运行契约从 `AgentPorts` / `run_turn` 演进为 `AgentContext`、`AgentLoopConfig` 和可继续执行的 Agent loop API，调用方迁移到新的核心入口。
- 将 core 消息收敛为 Agent Runtime 消息，移除 provider 原始参数解析、持久化树关系和具体工具输出字段等职责。
- 将模型调用、工具执行和 Agent 生命周期事件整理为明确的 core 契约；Session 生命周期、压缩和恢复事件不再属于 core Agent 事件。
- 将安全确认、Memory、MCP、Skill 和摘要器改造成 core 可消费的通用扩展点或上层适配器。
- 统一工具执行器端口与运行时装配，支持并发模式、取消、超时、进度更新和稳定的结果顺序。
- 增加 `transform_context`、`before_tool_call`、`after_tool_call` 和 `should_stop_after_turn` 等扩展钩子，保持主 ReAct 循环不感知具体扩展。
- 由 `session.AgentSession` 负责持久化、回滚、分支、压缩和 Session EventBus；core Agent 只维护内存上下文与运行状态。
- 删除或迁移当前 core 中无调用方、职责重复或绑定具体应用实现的兼容代码，并更新组合根、Session、测试和架构文档。

## Capabilities

### New Capabilities

<!-- None: this change refines the existing core capability. -->

### Modified Capabilities

- `core`: 将 Agent 编排从应用耦合的 ReAct 函数调整为纯内存、可扩展、可继续执行的 Agent Runtime，并重新划分事件、工具执行和消息契约。

## Impact

- 受影响代码：`src/codeagent/core/`、`src/codeagent/session/`、`src/codeagent/app/composition/`、`src/codeagent/tools/` 及相关测试。
- 受影响接口：`AgentPorts`、`ModelPort`、`StreamEvent`、`run_turn`、工具执行端口和 AgentEvent 类型；这是仓库内部 API 的破坏性重构。
- 不改变 AI 层的职责边界：`ai/` 继续只提供模型、Provider、Transport 和 Catalog，模型适配由组合根完成。
- 不要求引入新的第三方编排框架；实现继续保持离线可测和标准库依赖方向。
