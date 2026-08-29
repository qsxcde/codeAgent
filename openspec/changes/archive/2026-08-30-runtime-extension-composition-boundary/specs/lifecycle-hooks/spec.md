## MODIFIED Requirements

### Requirement: Hook 接入保持分层

生命周期 Hook、ContextTransformer、预算感知上下文扩展和工具前后置 Hook SHALL 只通过应用组合根装配具体实现；core 和 session SHALL 只依赖可共享的 provider-neutral 协议与结构化类型，不得发现、导入或实例化 provider、工具、MCP、Skill、memory 或 UI 的具体实现。应用组合根 SHALL 使用一个统一的运行时扩展集合将这些端口注入 AgentLoopConfig，并在创建 session、恢复 session、切换模型和 TUI 重建时保留同一组扩展及其顺序。

#### Scenario: 核心运行不依赖具体扩展

- **WHEN** 不提供任何扩展或提供仅实现协议的测试扩展
- **THEN** Agent Runtime 可以独立运行，core 不加载 provider、tools、MCP、Skill、memory 或 UI 实现

#### Scenario: 组合根统一注入扩展

- **WHEN** 应用组合根收到 ContextTransformer、上下文 preparer、工具 Hook、生命周期 Hook 和超时配置
- **THEN** 它们被归一为一组运行时扩展并注入 AgentLoopConfig，Hook 顺序和每个扩展的对象身份保持不变

#### Scenario: 会话恢复保留扩展

- **WHEN** SessionManager 创建、恢复或切换一个驻留会话
- **THEN** 新会话继续使用组合根提供的同一组运行时扩展，不因模型配置重建而静默丢失

#### Scenario: TUI 模型重建保留扩展

- **WHEN** TUI 执行 provider、model 或 effort 切换并重建 runtime
- **THEN** 新配置继续携带同一组扩展，旧 runtime 关闭和新 runtime 装配不改变扩展顺序

#### Scenario: 分层边界可验证

- **WHEN** 对 core 和 session 的源码导入图执行架构检查
- **THEN** 不存在指向 app、provider、tools、MCP、Skill、memory 或 UI 具体实现的反向导入，具体实现只出现在 app/composition 装配路径
