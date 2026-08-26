## Context

当前 `session` 层已经完成基础职责分离，但边界仍不完整：`AgentSession` 同时协调运行、事件、回滚、压缩和持久化；`SessionRuntime` 同时负责 core Agent 适配、确认响应和事件转换；`JsonFileStore` 同时负责 JSONL、记录解析、文件锁、索引、用量和分叉。现有公共行为与 JSONL v1 格式由会话、存储和回归测试共同约束。

本设计只做内部模块重组。保留 `codeagent.session` 与 `codeagent.session.store` 的稳定导出，避免在结构迁移过程中扩大 API 变更范围。

## Goals / Non-Goals

**Goals:**

- 建立清晰的会话 API、运行控制、事件、持久化、压缩和导航边界。
- 让 `AgentSession` 成为轻量公共 façade，避免继续增长为全能协调器。
- 让持久化记录拥有统一模型、编解码和版本校验入口。
- 让文件后端与内存后端共享协议和记录语义，同时保留各自的 I/O 策略。
- 保持现有事件、恢复、分叉、压缩、回滚、usage、模型切换和 JSONL 文件格式行为。
- 通过依赖边界测试防止 session 子模块循环依赖或反向依赖 `ai`、`tools`、`config`。

**Non-Goals:**

- 不新增用户可见会话功能，不改变 JSONL v1 的字段名或 entry 类型。
- 不在本变更中实现新的记忆、MCP、Skill 或模型能力。
- 不把 `SessionManager` 拆成多个过细的对象，也不为每种记录建立独立包。
- 不在本变更中改变“最近会话”的既有选择语义；相关行为只建立回归基线。
- 不强制引入新的数据库、跨进程锁库或第三方持久化依赖。

## Decisions

### 1. 以职责域建立目录，不以类数量建立目录

目标结构为：

```text
src/codeagent/session/
├── __init__.py
├── manager.py
├── session.py
├── runtime/
│   ├── __init__.py
│   ├── controller.py
│   ├── confirmation.py
│   ├── event_mapper.py
│   └── error_policy.py
├── events/
│   ├── __init__.py
│   └── bus.py
├── persistence/
│   ├── __init__.py
│   ├── protocol.py
│   ├── models.py
│   ├── records.py
│   ├── codec.py
│   ├── jsonl_store.py
│   ├── memory_store.py
│   ├── index.py
│   ├── locking.py
│   └── commit.py
├── compaction/
│   ├── __init__.py
│   ├── policy.py
│   ├── summarizer.py
│   └── details.py
└── navigation/
    ├── __init__.py
    └── tree.py
```

现有 `manager.py`、`session.py`、`tree.py` 和 `bus.py` 中已经有较完整的职责，不强行按行数拆分；只有当一个模块同时包含两个独立变化原因时才迁移到子包。

### 2. `AgentSession` 保留公共 façade，运行状态迁移到 runtime

`session.py` 只保留会话身份、历史、配置、摘要状态和对外操作入口。运行过程迁移到 `runtime/controller.py`，确认请求迁移到 `runtime/confirmation.py`，core 事件到 session 事件的转换迁移到 `runtime/event_mapper.py`，HTTP/provider 相关的友好错误处理迁移到 `runtime/error_policy.py`。

运行器以协议或工厂形式注入，session 不直接决定具体 Agent 实现。这样仍可调用现有 core ReAct Agent，但未来替换循环实现不会改变会话状态对象。

### 3. 持久化按“协议、记录、后端、索引、提交”分层

- `persistence/protocol.py`：`SessionStore` 端口。
- `persistence/models.py`：`SessionRef`、`UsageStats`、`CompactionState` 等领域模型。
- `persistence/records.py`：header、message、meta、usage、model change、compaction 的内部记录模型。
- `persistence/codec.py`：记录与 JSON 的双向转换、版本校验和损坏行策略。
- `persistence/jsonl_store.py`：文件读写、流式恢复、fork 和后端级锁协调。
- `persistence/memory_store.py`：测试/一次性运行的内存实现。
- `persistence/index.py`：可重建的轻量元数据索引。
- `persistence/locking.py`：路径锁和文件写入辅助。
- `persistence/commit.py`：成功轮次、usage、压缩记录的提交协调。

`JsonFileStore` 不再直接承担所有记录语义；`MemoryStore` 与 JSONL 后端都通过同一协议和记录模型表达行为。原 `store.py` 先作为 façade 保留，待调用方迁移完成后再删除或缩减为显式公共出口。

### 4. 压缩与导航作为 session 的独立能力域

压缩函数与摘要详情从单个 `compaction.py` 迁移到 `compaction/`，但仍只依赖消息模型和标准库。`navigation/tree.py` 只依赖 `persistence.models.SessionRef`，不再通过存储 façade 间接导入，保持纯函数和零 I/O。

### 5. 迁移采用 façade-first，避免一次性改动所有调用方

先建立新目录和新模块，再让旧入口转发到新实现；随后迁移 session 内部、组合根和测试的导入；最后删除已确认无人使用的旧私有入口。公共入口的兼容期限只覆盖稳定导入路径，不覆盖未声明的私有方法。

### 6. 先保持既有并发与持久化语义，再单独处理行为增强

本变更只把并发运行、确认取消、文件追加、索引失效和 fork 语义封装到明确模块并补充测试，不在重构过程中顺便改变“最近会话”算法、跨进程锁策略或 JSONL durability 策略。后续若要修正这些行为，应另立变更并更新对应规格。

## Risks / Trade-offs

- [拆分导致事件时序变化] → 保留现有事件映射和生命周期测试，迁移期间按事件序列做回归比较。
- [记录模型重构造成旧 JSONL 无法恢复] → 首先复用现有字段和版本校验，增加旧文件、损坏行、未知 entry 的回放测试。
- [ façade 与真实实现不一致] → façade 只做导出转发，不保留第二套业务逻辑；迁移完成后用 `rg` 检查调用方并删除未使用适配器。
- [运行器注入扩大组合根复杂度] → 先使用当前 core Agent 的最小适配器，保持 session 构造参数兼容，不引入新的外部依赖。
- [文件后端部分写入] → 本次只保留当前 append-only 语义并隔离提交协调；事务批写和跨进程锁作为后续独立可靠性变更。
- [内存/文件后端行为漂移] → 共享 `SessionStore` 协议、records 模型和行为测试，关键恢复、fork、压缩、usage 场景双后端运行。
