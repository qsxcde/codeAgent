## MODIFIED Requirements

### Requirement: Agent Runtime 扩展钩子

Agent Runtime SHALL 在每次模型请求前提供 `transform_context` 上下文转换点,并在工具执行前后提供 `before_tool_call`、`after_tool_call` 钩子;扩展可以修改本次模型可见上下文、阻止或修饰工具结果,但不得直接依赖 AI provider、Session 存储、MCP 客户端或 Skill 文件格式。对于需要预算信息的上下文扩展,Runtime SHALL 提供与 provider、session 和工具实现解耦的请求预算视图;扩展返回的上下文 SHALL 只作用于当前请求,不得改写持久化历史。已有只接收消息列表的 `transform_context` 扩展 SHALL 继续可用。扩展异常 SHALL 产生可诊断的 Agent 错误并遵循取消与回滚语义。

#### Scenario: 上下文扩展

- **WHEN** 注册了 `transform_context` 扩展
- **THEN** 每次模型请求前扩展可以基于当前消息生成模型可见上下文,而不修改 session 持久化的原始消息

#### Scenario: 预算感知上下文扩展

- **WHEN** 注册了需要预算信息的上下文扩展
- **THEN** 扩展收到中立的请求预算视图并可以生成当前请求的临时上下文,不得要求 core 直接提供 provider、session、MCP 或 Skill 具体实现

#### Scenario: 工具前置拦截

- **WHEN** `before_tool_call` 扩展阻止某个调用
- **THEN** 该调用不执行并生成结构化错误结果,同批其它调用按正常策略处理

#### Scenario: 工具结果后处理

- **WHEN** `after_tool_call` 扩展修改工具结果或声明终止后续模型请求
- **THEN** Agent 使用修改后的结果完成当前 turn,并按终止决策决定是否继续下一次模型请求

#### Scenario: 扩展异常

- **WHEN** 上下文或工具扩展抛出异常
- **THEN** Agent 发出带错误类型和阶段信息的错误事件,调用方可以回滚本轮且不得静默继续执行

#### Scenario: 预算计算失败

- **WHEN** 预算感知扩展无法解析请求组成或收到不确定的模型窗口
- **THEN** Runtime 发出带阶段和不确定性信息的诊断错误或受控结果,不得把未确认的预算当作精确值继续发送请求
