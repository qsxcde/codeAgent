## Context

父级 `AgentSession` 当前只持久化成功回合产生的 `Message`、usage 和压缩记录；`delegate` 的结构化 `ToolResult.details` 在转换为 `Message` 时被丢弃。V5-06/V5-07 已经提供了有界的父级 Subagent 事件和 TUI 实时投影，但事件没有恢复入口，临时 child session 也明确使用 `store=None`。本设计沿用 JSONL 为唯一事实源、索引为派生缓存、同步存储经异步边界访问以及生产文件规模限制。

## Goals / Non-Goals

**Goals:**

- 在父会话 JSONL 中保存可恢复的有限委派运行事实和结构化结果摘要。
- 让运行中断后的记录在恢复时明确变成不可恢复的 `abandoned`，而不是重新启动或显示为活动运行。
- 让 JsonFileStore、MemoryStore、同步事件流和异步会话收尾具有一致语义，并保持旧注入式 store 可用。
- 让 TUI 普通恢复和大历史后台恢复都能显示独立的委派块，同时不增加父普通消息或子 transcript。

**Non-Goals:**

- 不持久化 child session 的完整消息、工具输出、提示词或可变运行对象。
- 不实现跨进程重新接管子运行、子任务搜索、并行调度或新的 `/subagents` 命令。
- 不将 Subagent 运行记录计入父会话的普通消息父链、标题、最近活动时间或累计 usage。

## Decisions

### 1. 使用独立 `subagent` entry 和 session-owned record model

在 `session/persistence` 增加 `SubagentRunRecord` 数据模型及其 JSONL codec。entry 使用 `type="subagent"`，记录 `id`、`timestamp`、`delegationId`、`parentRunId`、`childRunId`、`attemptId`、`profile`、`taskLabel`、`status`、`phase`、`summary`、`reasonCode`、`diagnostics`、`cleanupUncertain` 以及有界的 `result` 字段。`result` 只保存 JSON-safe 的 summary、failure、findings、evidence、usage 和 artifact 引用；所有字符串、列表和序列化大小都在 session 边界再次截断/校验。

选择独立 entry 而不是把 details 塞进 `Message`，是因为委派事实不是模型上下文消息，且 core 的 `Message` 不应依赖 session 持久化语义。选择父会话 entry 而不是 child 文件，是因为 V5-08 只要求父会话可解释结果；child factory 继续传 `store=None`，因此 `SessionStore.list()` 永远不会看到临时子会话。

### 2. 在 SessionEventMixin 建立唯一的记录观察点

`AgentSession._emit()` 已经是父级事件归一化和 EventBus 发布的共同入口；它将匹配父 run 的 `SUBAGENT_QUEUED`、`SUBAGENT_STARTED`、关键状态变化的 `SUBAGENT_PROGRESS` 和 `SUBAGENT_FINISHED` 交给 `SessionPersistence`。记录器按 `delegation_id` 做内存去重：同一非终态签名只追加一次，首个有效终态后忽略所有迟到/冲突记录。它只持久化状态/阶段/身份/短诊断，不持久化进度 payload 中的完整 child 内容。

事件入口保持同步且不直接做文件 I/O。`SessionPersistence` 将每条待写记录排入同一异步锁保护的 `AsyncPersistenceBoundary`，并在 `SessionRunCoordinator` 的提交前和最终收尾阶段 drain；这样 JSONL 写入、锁和 fsync 不阻塞事件循环，终态记录在父回合结束前有确定的成功/失败结果。记录写失败只进入有界运行诊断，不改变父 Agent 的主运行结果。

### 3. 扩展 store port，但对旧实现能力探测

`SessionStore` 增加 `append_subagent_record()` 和 `load_subagent_records()` 端口；JsonFileStore 追加 JSONL 并让现有索引逻辑忽略该 entry，MemoryStore 使用独立的 per-session record 列表。`SessionPersistence` 读取和写入时使用 `getattr` 能力探测，使现有测试 double 或外部注入的旧 store 在缺少新端口时仍可正常恢复普通消息。

Subagent entry 不更新 `lastActivityAt`，不进入 usage 聚合、标题派生或压缩消息切点。fork 继续只复制既有消息/压缩语义，不复制临时运行记录；分叉后的普通消息仍包含父级已经提交的有限工具结果文本。

### 4. 恢复时按 delegation_id 折叠并在内存中标记 abandoned

加载记录采用流式读取，按首次出现顺序保留每个 `delegation_id` 的最新非终态或首个终态。有效终态包括现有运行终态；非终态 `queued/starting/running/waiting_confirmation/cancelling` 在返回恢复快照时转换为持久化视图专用的 `abandoned`，设置 `reasonCode=process_restarted`、`phase=recovered` 和有限诊断，并保留 `cleanupUncertain` 的诚实标记。该转换只发生在恢复内存结果中，不回写 JSONL，避免只读恢复产生隐藏副作用。

恢复层不会创建 runner、child Session 或新的活动任务；`AgentSession.is_running` 仍为 false。缺失、未知或损坏的 Subagent entry 被局部跳过并计入已有恢复诊断，不影响旧消息恢复；没有任何新 entry 的旧文件返回空记录集合。

### 5. TUI 使用专用 hydration 路径

`RestoredSessionState` 和 `AgentSession` 暴露恢复后的 `subagent_records`。`TuiModel.hydrate_history()` 接收可选记录，使用专用的 `hydrate_subagent_records()` 创建默认折叠的 `SubagentBlock`，绕过实时事件所需的 current parent run 校验，但仍复用块的有界字段、终态标签和结果统计。记录块追加在恢复普通消息之后，不转成 assistant/tool/error 消息。

大历史恢复的后台快照同时携带记录，并将恢复模型的 Subagent projection 一并迁移到当前模型；会话切换仍先清空旧 projection。恢复的 `abandoned` 记录不参与当前运行的 running/waiting 计数、不显示活动动画，已完成/失败结果也不会再次触发事件或写入记录。

### 6. 以双后端和故障注入固定兼容边界

测试覆盖 JSONL round-trip、旧 JSONL 无 entry、非终态重启标记、重复/迟到终态、记录边界过滤、索引和最近活动不受影响、MemoryStore 对齐、事件循环不被同步 I/O 阻塞、父回合取消/提交失败以及 TUI 普通和大历史恢复。所有测试使用 FakeSession/FakeStore/tmp_path，不连接真实 provider、MCP 或网络。

## Risks / Trade-offs

- [事件记录异步写入与父消息提交交错] → 使用单一写锁和提交前 drain；最终收尾再次 drain，记录失败单独诊断且不修改父主结果。
- [进程在 queued 记录 fsync 前立即崩溃] → V5-08 只承诺对已落盘事实诚实恢复；没有任何落盘事实时不会虚构子任务，后续版本再考虑更强的 WAL/跨进程接管。
- [记录数量随长会话增长] → 只记录生命周期/关键状态变化，不记录每个 child event；每条字段、结果列表和诊断都有固定上限，读取采用流式折叠。
- [新 entry 损坏或字段不完整] → 按记录局部跳过并产生稳定恢复诊断；header、版本和普通消息的既有恢复策略不改变。
- [恢复块与普通消息缺少精确位置关系] → V5-08 只承诺父会话能看到有界结果及状态；记录投影放在恢复 transcript 的末尾，精确时间线和可搜索子 transcript 留给后续版本。

## Migration Plan

1. 先实现记录模型、codec、双后端端口和恢复折叠测试，再接入父事件异步观察和 `RestoredSessionState`。
2. 接入 TUI 普通/后台恢复，补充去重、abandoned、旧文件和父取消回归。
3. 运行 session、Subagent、TUI 的窄测试，再运行分层测试、全量测试、Ruff、规模扫描、OpenSpec 严格校验、差异检查和构建。
4. 同步 `subagent-run-records` 与 `sessions` 主规格并更新 v0.5/架构文档。回滚时可移除记录消费和写入路径；既有 JSONL message/compaction entry 无需迁移。
