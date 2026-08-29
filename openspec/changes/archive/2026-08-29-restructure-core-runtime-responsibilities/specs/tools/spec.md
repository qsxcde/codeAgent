## ADDED Requirements

### Requirement: AgentTool 显式适配

工具层或应用组合根 SHALL 为每个内建工具和已加载的 MCP 工具提供显式的 `AgentTool` 适配入口。适配后的工具 SHALL 暴露稳定的名称、描述和 provider-neutral 参数定义,并通过 `execute(tool_call_id, arguments, signal, on_update)` 处理调用,返回 core 可消费的统一工具结果。core 不得读取具体工具的输入 schema、执行方法或安全配置来推断适配方式。

#### Scenario: 内建工具完成适配

- **WHEN** 组合根装配内建 read、write、edit、bash、grep、find、ls、skill 工具
- **THEN** 每个工具都以 `AgentTool` 形态传入 Agent Runtime,名称、描述、参数定义和执行结果保持原有语义

#### Scenario: MCP 工具完成适配

- **WHEN** 组合根加载一个 MCP 工具
- **THEN** MCP 工具以 `AgentTool` 形态追加到运行时工具列表,名称仍遵守 `mcp__<server>__<tool>` 规则,core 无需知道 MCP 客户端类型

#### Scenario: 适配器传递取消与进度

- **WHEN** Agent Runtime 对适配后的工具发出取消或进度回调
- **THEN** 适配器将取消信号和进度回调传递给底层工具,并把真实清理状态转换为统一工具结果

#### Scenario: 旧工具不能绕过适配

- **WHEN** 一个只提供历史 `Args`/`invoke` 接口的工具未经过显式适配
- **THEN** 组合根不得将其直接挂载到 Agent Runtime,系统返回可诊断的装配错误而不是依赖 core 的隐式兼容
