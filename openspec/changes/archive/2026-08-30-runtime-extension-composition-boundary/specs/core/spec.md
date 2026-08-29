## MODIFIED Requirements

### Requirement: Agent Runtime 扩展钩子

Agent Runtime SHALL 只通过 provider-neutral 的配置协议接收 ContextTransformer、预算感知上下文扩展、工具 Hook 和生命周期 Hook；core 不得发现、实例化或导入任何具体 provider、工具、MCP、Skill、memory 或 UI 实现。应用组合根负责把具体实现归一并注入运行配置，运行时只执行已注入的协议对象，且不因 session 恢复、模型切换或 TUI 重建而改变其顺序和语义。其余上下文转换、工具 Hook 异常、超时、取消和回滚规则保持既有契约。

#### Scenario: 上下文扩展

- **WHEN** 注册了 `transform_context` 扩展
- **THEN** 每次模型请求前扩展可以基于当前消息副本生成模型可见上下文，而不修改 session 持久化的原始消息

#### Scenario: 预算感知上下文扩展

- **WHEN** 注册了需要预算信息的上下文扩展
- **THEN** 扩展收到中立的请求预算视图并可以生成当前请求的临时上下文，不得要求 core 直接提供 provider、session、MCP 或 Skill 具体实现

#### Scenario: 扩展只执行注入对象

- **WHEN** Agent 收到由应用组合根注入的运行时扩展集合
- **THEN** core 只调用集合中的协议对象，不自行发现或实例化任何具体扩展实现

#### Scenario: 上下文扩展超时或非法返回

- **WHEN** 上下文扩展超过配置时限或返回不是有效消息集合
- **THEN** Agent 产生带扩展阶段、错误码和原因的上下文准备错误，且不调用模型

#### Scenario: 上下文扩展取消

- **WHEN** 运行在等待上下文扩展时被取消
- **THEN** 取消向上游传播，扩展不会被包装成普通错误，且不会留下悬挂的模型请求

#### Scenario: 工具前置拦截

- **WHEN** `before_tool_call` 扩展阻止某个调用
- **THEN** 该调用不执行并生成结构化错误结果，同批其它调用按正常策略处理

#### Scenario: 工具结果后处理

- **WHEN** `after_tool_call` 扩展修改工具结果或声明终止后续模型请求
- **THEN** Agent 使用修改后的结果完成当前 turn，并按终止决策决定是否继续下一次模型请求

#### Scenario: 扩展异常

- **WHEN** 上下文或工具扩展抛出异常
- **THEN** Agent 发出带错误类型和阶段信息的错误事件，调用方可以回滚本轮且不得静默继续执行

#### Scenario: 预算计算失败

- **WHEN** 预算感知扩展无法解析请求组成或收到不确定的模型窗口
- **THEN** Runtime 发出带阶段和不确定性信息的诊断错误或受控结果，不得把未确认的预算当作精确值继续发送请求
