## Context

See `proposal.md` for the motivation. 当前 JsonFileStore 通过 `SessionIndex` 缓存标题、模型、时间和父级元数据，MemoryStore 维护等价的内存引用；两者的 `list()` 尚未接受查询条件，TUI `/sessions` 只支持列表、创建、恢复和 id 切换。运行状态只存在于驻留的 `AgentSession`，不应为了筛选而写入 JSONL。

## Goals / Non-Goals

**Goals:**

- 建立对两个存储后端一致的只读会话查询值对象和匹配语义。
- 让索引命中路径直接用缓存元数据筛选，索引失效时沿用重建和损坏会话隔离策略。
- 让 SessionManager 将驻留运行态叠加到列表引用，并让 TUI 提供可发现、可诊断的搜索/筛选入口。

**Non-Goals:**

- 不新增 JSONL entry、归档/删除状态或跨进程持久化运行结果；这些属于后续 V4-25/V4-26。
- 不实现全文搜索、正则表达式、模糊评分、分页或新的会话选择器组件。
- 不改变现有列表排序、最近恢复、树形显示和会话切换行为。

## Decisions

### 1. 查询条件使用值对象并沿存储端口传递

新增不可变 `SessionQuery`，字段为 `text`、`model`、`after`、`before` 和 `status`。文本和模型匹配使用大小写折叠，时间使用项目现有 ISO 时间字符串的字典序；构造时拒绝反向时间范围和未知状态。`SessionStore.list(query=None)` 保留默认参数，旧调用方无需修改。

### 2. 持久化筛选只依赖索引元数据

JsonFileStore 的 `list(query)` 继续通过 `get()` 读取合法索引，随后对 `SessionRef` 做纯匹配；索引无效时 `get()` 自动重建，回源扫描只发生在必要路径。MemoryStore 直接对内存引用应用同一匹配器。这样不改变 JSONL 格式，也不需要为每种查询维护另一份缓存。

### 3. 运行状态由 SessionManager 叠加

`SessionRef` 增加只读 `status` 字段。存储后端对持久化会话默认返回 `idle`；SessionManager 列表读取后根据驻留 session 的 `is_running` 和 `last_outcome` 覆盖为 `running`、`completed`、`failed` 或 `cancelled`，再执行 status 条件。未驻留的会话不从历史事件推断已结束状态，重启后保持 `idle`。

### 4. TUI 采用可组合的 key=value 查询语法

`/sessions search <text>` 负责低门槛标题/id 搜索；`/sessions filter` 使用 `shlex` 支持带空格的引号值，允许组合 `title`、`model`、`status`、`after`、`before`。查询结果使用紧凑表格式展示，不影响现有 `/sessions list` 的树形输出；异常只追加信息块，不进入对话运行路径。

### 5. 查询与状态均保持安全降级

空条件、非法时间或未知状态在 TUI 命令层拒绝；存储索引异常沿用现有回源重建，单个坏文件沿用列表隔离。查询不写 JSONL、不刷新活动时间、不改变当前 session，也不触发模型或工具。

## Risks / Trade-offs

- [Risk] 时间字符串查询要求输入与现有 ISO 格式兼容 → TUI 只接受 `YYYY-MM-DD` 或 ISO-8601 前缀并给出明确错误；内部比较保持确定性。
- [Risk] 重启后无法知道最后一次运行是成功还是失败 → 明确归类为 `idle`，避免把未持久化运行结论伪装成事实。
- [Risk] 每次列表仍需遍历会话文件名 → 每个会话的合法索引读取只触发小型元数据访问；进一步分页/全局索引留给 V4-27。

## Migration Plan

无需迁移。旧 JSONL 和旧索引继续可读；新增的 `status` 是内存引用字段，不改变文件格式。回滚代码后，新增查询入口消失但历史会话和索引不受影响。
