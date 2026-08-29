## Why

当前 core 已通过 provider-neutral 协议接收生命周期 Hook 和上下文扩展，但应用组合入口只零散透传部分回调；会话恢复、模型切换和 TUI 重建容易丢失 ContextTransformer、preparer、工具 Hook 或超时配置。需要一个明确的组合根边界，让具体实现只在 `app/composition` 进入 Runtime，而 core/session 只消费协议。

## What Changes

- 在 `app/composition` 提供统一的 RuntimeExtensions 装配对象，承载 ContextTransformer、预算上下文扩展、工具 Hook、生命周期 Hook 和上下文扩展超时。
- 让 runtime、session manager、会话恢复和 TUI 模型重建沿同一扩展对象透传，避免切换模型或重建资源时丢失扩展。
- 保留现有 `lifecycle_hooks` 等参数作为兼容入口；新组合对象在组合根归一化后注入 `AgentLoopConfig`。
- 增加契约测试，证明 core 不导入 app、provider、tools、MCP、Skill 或 UI 的具体实现，且组合根注入的扩展身份和顺序稳定。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `lifecycle-hooks`: 明确应用组合根统一装配扩展，运行时、session 和 TUI 重建保持扩展不丢失。
- `core`: 明确 core 只接收 provider-neutral 扩展协议，不负责发现或实例化具体实现。

## Impact

- 影响 `src/codeagent/app/composition/runtime/`、`app/composition/session/`、`app/composition/tui/` 的工厂参数和恢复链路。
- 新增 app 组合对象及其公开导出；现有直接构造 Agent/AgentSession 的嵌入和测试路径保持可用。
- 增加 app/contract 回归测试与架构文档说明，不新增依赖，不改变事件或持久化格式。
