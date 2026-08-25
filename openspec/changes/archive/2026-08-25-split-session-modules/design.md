## Context

当前 session 层已经有 `bus.py`、`compaction.py`、`manager.py` 和 `tree.py` 等边界，但 `store.py` 仍同时包含存储契约、记录格式、文件后端、索引和内存后端，`session.py` 则同时管理 AgentSession 的状态、异步运行、持久化和压缩。现有调用方直接从 `codeagent.session.store` 和 `codeagent.session.session` 导入公共符号；JSONL、索引和事件语义已经由现有测试固定下来。

本设计是内部模块重组，不迁移持久化数据，不引入新的外部依赖，也不改变公共行为。

## Goals / Non-Goals

**Goals:**

- 将存储模型、JSONL 编解码、文件后端和内存后端分离，降低单文件耦合。
- 将 AgentSession 的运行控制和持久化协调隔离，同时保留 AgentSession 作为稳定公共门面。
- 保持 `codeagent.session.store`、`codeagent.session.session.AgentSession` 和 `DEFAULT_CONTEXT_WINDOW` 的现有导入路径。
- 保持 JSONL/索引格式、文件权限、锁、原子写入、压缩恢复、分叉、延迟持久化和失败回滚语义。
- 让每个新模块可以在不启动模型或终端的情况下进行单元测试。

**Non-Goals:**

- 不改变 SessionStore 的公共方法签名或新增用户可见能力。
- 不迁移或重写已有会话 JSONL、索引文件或压缩记录。
- 不重做索引算法、消息格式、上下文压缩算法或事件协议。
- 不将 session 层改为依赖 `ai`、`tools`、`config`，也不把 TUI 逻辑下沉到 session 层。

## Decisions

### 1. 使用扁平内部模块，并保留 `store.py` 兼容门面

目标结构为 `store_models.py`、`store_codec.py`、`json_file_store.py`、`memory_store.py` 和 `store_index.py`。`store.py` 只重新导出原有公共符号。

选择扁平模块是为了避免同时存在 `session/store.py` 和 `session/store/` 包目录造成导入解析歧义。保留门面可以让现有 manager、CLI、TUI 和测试继续使用旧导入路径。

备选方案是直接把 `store.py` 改成 `store/` 包，但这会扩大导入路径变更范围，且需要处理文件与包同名迁移，不采用。

### 2. 先按边界搬迁，再抽象索引

第一步只移动现有实现：

- `store_models.py` 放置 `UsageStats`、`SessionRef`、`CompactionEntry`、`CompactionState` 和 `SessionStore`。
- `store_codec.py` 放置 `_now`、标题派生、消息序列化/反序列化和 header 校验。
- `json_file_store.py` 承载 `JsonFileStore`。
- `memory_store.py` 承载 `MemoryStore`。

第二步再把索引构建、校验、原子写入、失效和增量应用抽到 `store_index.py`。索引内部仍使用现有 JSON 字段形状，避免在同一变更中同时引入新的索引数据模型。

备选方案是第一步就引入全新的类型化索引对象，虽然更整洁，但会同时改变内部数据形状和错误边界，回归风险更高。

### 3. `JsonFileStore` 保留文件一致性边界

路径锁必须继续覆盖 JSONL 追加以及索引更新；`_append` 的顺序保持为写入 JSONL、设置文件权限、更新或重建索引、失败时使索引失效。分叉继续使用临时文件、逐行复制、权限收敛和 `os.replace`，源文件保持只读。

索引模块通过显式传入 entry 迭代器、源指纹和文件权限回调与后端协作，不反向依赖 `JsonFileStore`，避免循环导入。

### 4. `AgentSession` 采用组合而非 mixin

新增两个内部协作者：

- `SessionRuntime`：封装 `run_turn` 调用、current task、注入/确认队列、运行 id、副作用状态、取消和失败诊断。
- `SessionPersistence`：封装会话恢复、延迟创建 header、成功轮次消息和 usage 提交、context token 写入以及失败回滚。

`AgentSession` 继续持有会话核心状态和公开属性，并负责把 runtime 结果交给 persistence；协作者通过显式参数和结果对象通信，不直接互相访问私有字段。

选择组合是为了避免 mixin 隐式依赖 `_history`、`_summary`、`_current_task` 等字段，也避免把异步生命周期拆成多个难以追踪的继承层。

### 5. 保持公共符号和内部兼容别名

`store.py` 继续提供现有 `__all__`；`session.py` 继续提供 `AgentSession`、`DEFAULT_CONTEXT_WINDOW`、压缩常量和现有测试可访问的错误转换入口。内部新模块的类名不作为公共 API 扩展，除非后续单独提出变更。

## Risks / Trade-offs

- [循环导入] 新模块互相引用可能破坏 session 层装配 → 采用单向依赖：models/codec → backends/index，runtime/persistence → core、store 门面；运行 `tests/test_decoupling.py` 和导入烟测。
- [索引一致性回归] 抽取索引后可能遗漏路径锁、mtime/size 指纹或失败失效 → 保留 `_append` 的一致性边界，增加损坏、过期、更新失败和并发追加测试。
- [异步运行状态丢失] `SessionRuntime` 拆分可能改变取消、确认和 cleanup 状态传播 → 通过现有 session 回归测试并增加运行结果/事件关联断言。
- [延迟持久化回归] 协作者拆分可能提前创建空会话或写入失败轮次 → 保持 `defer_persistence` 和 `_ensure_persisted` 的单一入口，覆盖空会话、成功、失败和取消路径。
- [公共导入破坏] 调用方仍直接导入 `codeagent.session.store` 的符号 → `store.py` 作为兼容重导出层，增加公共导入契约测试。
- [文件数量增加] 模块数量增多会增加导航成本 → 每个模块只保留单一职责，并在模块 docstring 中注明层级和依赖约束。

## Migration Plan

1. 创建目标模块，先按原实现搬迁模型、编解码和两个后端；保持 `store.py` 重导出并运行 store 测试。
2. 抽取索引逻辑，验证索引命中、重建、失效、原子写入和 JSONL 回退行为。
3. 创建 `SessionRuntime` 和 `SessionPersistence`，让 `AgentSession` 以门面方式委托，运行 session、manager 和 container 测试。
4. 运行完整测试套件和分层导入检查，确认公共 API、JSONL 文件和索引均无需迁移。

每一步都可以通过恢复旧模块导入和删除新增内部模块回滚；由于不修改持久化文件格式，回滚不需要数据恢复或迁移脚本。
