## Why

`src/codeagent/session` 已经同时承载会话生命周期、ReAct 运行控制、事件转换、确认响应、JSONL 存储、索引、压缩和 fork 导航。功能契约基本稳定，但 `session.py` 与 `json_file_store.py` 仍是大型协调器，存储记录解析也分散在多个实现中，继续增加能力会放大耦合和迁移成本。

现在按职责重新归并，可以在不改变用户可见会话行为和文件格式的前提下，为运行控制、持久化和上下文能力建立清晰边界。

## What Changes

- 将 `session` 重组为会话 API/生命周期、运行控制、事件、持久化、压缩和导航几个职责域。
- 从 `AgentSession` 中抽取运行状态机、确认管理、事件映射和错误策略；保留 `AgentSession` 作为稳定公共会话入口。
- 将 JSONL 记录模型、编解码、存储协议、文件后端、内存后端、索引、锁和提交协调归入 `persistence/`。
- 统一 `message`、`meta`、`usage`、`model_change`、`compaction` 等记录的内部表示和解析边界。
- 将事件总线归入 `events/`，将 fork 树视图归入 `navigation/`。
- 保持现有公共导入、JSONL 版本与 entry 结构、恢复/分叉/压缩语义、事件契约和 `SessionStore` 行为不变；迁移完成后删除不再需要的内部兼容入口。
- 补充会话并发运行、确认响应清理、最近会话选择、存储一致性和模块依赖边界的回归测试，确保重构不改变既有语义。

## Capabilities

### New Capabilities

无。本变更只调整内部模块边界，不引入新的用户可见能力。

### Modified Capabilities

无。现有会话行为和持久化格式保持不变；本变更通过 `skip_specs: true` 声明为纯内部重构。

## Impact

- 受影响代码：`src/codeagent/session/` 全部模块、`app/composition` 中的会话装配、会话相关测试和内部导入路径。
- 公共 API：短期保留 `codeagent.session`、`codeagent.session.store` 等稳定入口；内部模块迁移完成后再删除未使用的兼容入口。
- 数据兼容：不改变现有 JSONL v1 文件、消息 parent 链、压缩记录、usage 记录和索引重建语义。
- 依赖边界：session 继续不依赖 `ai`、`tools`、`config`；持久化只依赖消息模型和标准库，具体 core Agent 装配由组合根负责。
