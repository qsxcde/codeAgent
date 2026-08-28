## MODIFIED Requirements

### Requirement: Canonical AI imports

系统 SHALL 通过稳定且唯一的规范路径提供 AI 层能力：模型消息、响应、工具定义、流事件和相关协议从 `codeagent.ai.model` 导入，SSE 解析器从 `codeagent.ai.transport.sse` 导入；provider、transport 和 catalog 的现有规范子包 SHALL 继续可用。AI 模型契约 SHALL 接受规范化的模型可见数据；应用组合根负责 provider 选择、客户端装配以及具体工具到工具定义的转换，AI 基础设施包不承担应用配置读取、客户端选择或具体工具适配职责。

#### Scenario: Import model contracts from canonical package

- **WHEN** 下游代码导入 `codeagent.ai.model`
- **THEN** 可以获得 `ChatClient`、`ChatMessage`、`ChatResponse`、`Provider`、`StreamEvent`、`StreamEventType`、`ToolCall`、`ToolDefinition` 和 `Transport` 等 AI 契约，且导出对象保持现有语义

#### Scenario: Import SSE parser from canonical transport package

- **WHEN** 下游代码导入 `codeagent.ai.transport.sse`
- **THEN** 可以获得 `SSEParser` 及其产生的规范流事件类型，解析多行 data、DONE、usage、thinking 和 tool-call delta 的行为保持不变

#### Scenario: Use application composition for client assembly

- **WHEN** 应用需要按 provider、model 或 reasoning effort 创建客户端
- **THEN** 应从 `codeagent.app.composition.model_selection` 使用对应装配入口，AI 基础设施包不承担应用配置读取或客户端选择职责

#### Scenario: Adapt a concrete tool outside the AI package

- **WHEN** 应用需要把内置工具或 MCP 工具暴露给模型
- **THEN** 组合层在调用 AI client 前将其转换为 `ToolDefinition`，AI 包不读取该工具的 `args_schema`、执行能力或安全配置
