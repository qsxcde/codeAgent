## Context

当前 `JsonFileStore` 已能在索引损坏或过期时回源重建，也会跳过非法 JSON 行，但这些事实没有向恢复层传递。`SessionPersistence.load()` 是所有 `AgentSession` 恢复的集中入口；header 缺失、版本不兼容或消息解码异常会以普通异常中断，TUI/CLI 因而无法区分可继续的降级与不可安全恢复。

## Goals / Non-Goals

**Goals:**

- 建立 MemoryStore 与 JsonFileStore 共用的、可序列化/可测试的恢复报告和值域。
- 在不改变 JSONL 记录格式的前提下识别坏行、无效消息、索引失效、压缩边界缺失、header 缺失和版本不兼容。
- 对安全范围内的问题局部恢复，对结构性问题拒绝激活，并向 TUI/CLI 传递原因与下一步。
- 诊断和恢复路径保持离线、只读原始会话；索引重建仍是允许的派生缓存写入。

**Non-Goals:**

- 不在本变更中设计新的 JSONL 版本、自动迁移器、回收站或原始文件修复器。
- 不自动删除坏行、不覆盖不兼容文件、不通过模型摘要来猜测丢失内容。
- 不把所有历史会话预先完整扫描以生成列表诊断；主动诊断和实际恢复时才扫描源文件。

## Decisions

### 1. 用 typed report 表达恢复结果

新增不可变的 `RecoveryDiagnostic` 与 `SessionRecoveryReport`，状态固定为 `healthy`、`degraded`、`unavailable`；诊断字段包含 `code`、`message`、`impact`、`action`，并带有效消息数与跳过记录数。相比让调用方解析异常文本，这能让 CLI/TUI 稳定展示，也让测试不依赖文案。

### 2. Store 提供报告，SessionPersistence 负责恢复策略

在 `SessionStore` 增加恢复报告查询端口。JsonFileStore 使用流式检查器读取源文件；MemoryStore 返回健康报告。`SessionPersistence` 在读取上下文前保存报告：`degraded` 继续用容错读取，`unavailable` 抛出携带报告的 typed error。这样持久化事实仍由 store 管理，是否激活 AgentSession 仍由会话层决定。

### 3. 安全范围内逐记录降级

非法 JSON 行、无法解码的 message 和不可用的 compaction cut 不阻断其余有效记录：分别跳过、保留有效消息、回退为全量可解析消息，并在报告中记录影响。header 缺失或版本不兼容无法确认格式，直接报告 unavailable。读取器不把缺失内容补成有效消息。

### 4. 通过既有入口传递而非新增后台服务

SessionManager 暴露按 id 查询报告；TUI 增加 `/sessions recovery <id>`，切换成功后的降级报告就地提示；headless 在 manager 恢复失败处捕获 typed error 并返回非零。报告采用同一 formatter，避免 TUI/CLI 对同一事实给出不同结论。

### 5. 索引失效保持 fail-open，但留下可见事实

索引缺失、损坏或指纹过期仍允许 JSONL 回源读取并重建索引；报告将其标记为可恢复的 degraded 诊断，说明这是派生缓存修复而非历史丢失。若索引重建失败，继续直接扫描，并把失败原因纳入报告。

## Risks / Trade-offs

- [Risk] 诊断检查与实际恢复可能需要两次流式扫描 → 保持逐行读取，不保留原始全文；仅在主动诊断/恢复时承担额外 I/O。
- [Risk] 跳过坏 message 可能让父级链出现断点 → 报告明确列出跳过数量和继续建议，恢复层不伪造父级关系；用户仍可备份原文件后手工迁移。
- [Risk] 旧版本/外部实现未实现新端口 → 为协议增加兼容 fallback，缺少报告能力的 store 返回健康/未知的保守结果，不改变既有恢复路径。
- [Risk] TUI 首次恢复错误发生在 manager adopt 之前 → 先生成报告并在 typed error 中携带，失败时不替换当前模型；已有大型 transcript 后台恢复错误仍沿用 `restore_failed` 运行态诊断。

## Migration Plan

1. 先补充 report 数据模型、JsonFileStore/MemoryStore 检查器和 SessionPersistence 恢复边界测试。
2. 接入 SessionManager、TUI `/sessions recovery` 与 headless 指定会话错误输出。
3. 更新 sessions/TUI 主规格、README、测试与 v0.4 进度说明。
4. 发布时不迁移 JSONL；旧文件首次读取按兼容规则报告并在需要时重建索引。若实现需回滚，删除新 UI 入口即可，原始 JSONL 仍可由旧读侧读取。
