## Why

`src/codeagent/session/store.py` 同时承担数据模型、JSONL 编解码、索引、文件后端和内存后端，已经超过 1,000 行；`session.py` 也把运行控制、持久化、压缩和错误诊断集中在一个会话类中。职责耦合使定位问题、编写单元测试和后续扩展变得困难。本变更在不改变现有行为和公共导入路径的前提下拆分模块，降低维护风险。

## What Changes

- 将会话数据模型与 `SessionStore` 协议抽到独立模块。
- 将 JSONL 编解码、header 校验和标题派生抽到独立模块。
- 将 `JsonFileStore` 与 `MemoryStore` 分离到各自的后端模块。
- 将文件索引逻辑在保持现有锁、指纹、原子写入和回退语义的前提下独立出来。
- 保留 `session.store` 作为兼容导出层，现有导入路径继续有效。
- 将 `AgentSession` 的运行控制和持久化协调拆成内部服务，由 `AgentSession` 继续作为稳定公共门面。
- 保持 JSONL 格式、索引格式、压缩恢复、分叉、延迟持久化、失败回滚和 MemoryStore/JsonFileStore 行为不变。
- 增加分层导入、行为等价和回归测试，确保重构不引入循环依赖或公共 API 破坏。

## Capabilities

### New Capabilities

无。本变更只调整内部模块组织，不引入新的用户可观察能力。

### Modified Capabilities

无。现有会话持久化和会话运行规范保持不变；该变更通过 `skip_specs: true` 声明为纯内部重构。

## Impact

- 主要代码：`src/codeagent/session/store.py`、`src/codeagent/session/session.py`，以及新增的 session 层内部模块。
- 兼容入口：`codeagent.session.store`、`codeagent.session.session.AgentSession`、`DEFAULT_CONTEXT_WINDOW` 和现有公开数据类型。
- 依赖关系：session 层仍只依赖 `core` 与同层模块，不引入对 `ai`、`tools` 或 `config` 的依赖。
- 测试范围：`tests/session/`、容器装配测试、CLI/TUI 的会话存储相关测试，以及完整测试套件。
- 持久化数据：不迁移、不重写既有 JSONL 或索引文件。
