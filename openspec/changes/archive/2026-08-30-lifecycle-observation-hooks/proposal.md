## Why

v0.4 已经有结构化运行事件，但扩展方仍需要自行解析不同层的事件流，无法用统一契约观察 turn、model、tool 和 session 的生命周期。现在建立只读观察 Hook，可以为后续审计、遥测和记忆扩展提供稳定接缝，同时保持 ReAct 主流程不被扩展逻辑改写。

## What Changes

- 新增 provider-neutral 的生命周期观察事件和 Hook 回调契约。
- 为 turn、model、tool 事件提供 `started`、`updated`、`finished` 三类生命周期阶段，并保证事件携带运行关联信息。
- 为 session 事件提供开始、更新和结束观察，补充稳定的 `session_id`。
- 在模型请求边界发布显式的模型开始和结束事件。
- 允许通过 AgentLoopConfig 注入多个观察 Hook，按注册顺序同步观察；Hook 返回值不参与主流程决策。
- 保持既有事件订阅和工具执行 Hook 的兼容行为；异常隔离、上下文转换和工具结果修改继续由后续变更分别定义。

## Capabilities

### New Capabilities

- `lifecycle-hooks`: 为 Agent Runtime 和 Session 提供只读的生命周期观察 Hook 契约。

### Modified Capabilities

- `core`: 补充模型请求生命周期事件，使核心运行事件可以被 Hook 稳定观察。

## Impact

- 影响 `core` 的事件契约、`AgentLoopConfig` 和 Agent 事件分发；不引入新的第三方依赖。
- 影响 session 的事件发布和组合根的配置入口，现有订阅方继续收到原有事件。
- 新增核心与 session Hook 回归测试，并同步 v0.4 迭代、架构和测试文档。
