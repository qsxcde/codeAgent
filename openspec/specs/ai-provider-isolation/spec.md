# ai-provider-isolation Specification

## Purpose

确保 AI 基础设施只消费规范化的模型请求数据，并使可复用客户端在并发调用、无效目录输入和兼容调用方式下保持隔离且可诊断。

## Requirements

### Requirement: Normalized model-visible tool definitions

AI client SHALL 只消费已规范化的 `ToolDefinition` 值作为模型请求中的工具定义。具体工具对象的 schema 提取和转换 SHALL 在 AI 包之外完成，AI 包不得依赖或探测具体工具的 `args_schema`、执行方法或权限信息。

#### Scenario: Send a normalized tool definition

- **WHEN** 调用方在模型请求中提供一个或多个 `ToolDefinition`
- **THEN** AI client 将这些定义序列化为 provider 请求格式，而不访问具体工具实现

#### Scenario: Tool schema conversion fails before the AI boundary

- **WHEN** 组合层无法把具体工具转换为规范化工具定义
- **THEN** 调用方获得包含工具标识和失败原因的可诊断错误，且不会向 provider 发送该请求

### Requirement: Request-scoped tool isolation

共享的 AI client SHALL 仅使用当前 `generate` 或 `stream` 调用明确传入的工具定义构造该请求。一个请求的工具定义不得出现在另一个并发或后续请求中。

#### Scenario: Concurrent requests use different tool sets

- **WHEN** 同一 client 并发发起两个携带不同工具定义的请求
- **THEN** 每个 provider 请求只包含自身调用传入的工具定义

#### Scenario: Existing bound-client call remains isolated

- **WHEN** 调用方通过兼容的 `bind_tools` 形式获得带默认工具定义的 client，并同时使用原 client 发起请求
- **THEN** 绑定结果不改变原 client 的默认请求内容，两个 client 的工具定义保持独立

### Requirement: Observable malformed catalog input

AI catalog SHALL 在容错跳过用户 `models.json` 中的非法 provider 或模型记录时输出可诊断信息，至少包含目录路径、记录位置或 provider 标识及跳过原因；其他合法记录仍 SHALL 被加载。

#### Scenario: Invalid record does not hide the reason

- **WHEN** 用户模型目录包含形状错误或字段类型错误的记录
- **THEN** 系统跳过该记录并记录可识别的诊断原因，同时继续加载同一文件中的合法模型

#### Scenario: Catalog file cannot be read

- **WHEN** 用户模型目录不存在、无法解码或 JSON 无效
- **THEN** 系统记录文件路径和读取失败原因，并回退为不含用户覆盖的目录
