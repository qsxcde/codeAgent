## Context

当前 `SubagentResult` 已经传递终态、摘要、失败和清理诊断，但结构化结果仍停留在应用层 `ToolResult.details` 之外；子 Session 的工具消息携带 `ToolOutputMetadata`，模型请求通过 `USAGE` 事件产生统一 token 形状，二者都可以在子运行结束时读取。core 不能依赖 session、ai 或 tools，因此稳定值对象必须放在 core，子会话事实的提取必须留在组合层。详见 `proposal.md` 和变更规格。

## Goals / Non-Goals

**Goals:**

- 建立可由 core、组合层和后续 TUI/持久化复用的不可变结构化结果契约。
- 将真实子会话已经产生的摘要、工具证据、用量和 artifact 引用转换为有界、JSON-safe 的父级结果。
- 保持旧 runner 的构造方式和当前失败/清理状态映射兼容，并确保越界数据在父上下文边界前被拒绝。
- 为后续 V5-06 事件展示和 V5-08 有限运行记录提供不依赖 transcript 的输入。

**Non-Goals:**

- 不在本阶段改变 JSONL 会话格式、恢复协议或 `/sessions` 列表。
- 不从自然语言摘要猜测 findings，不要求模型输出新的 JSON 协议，也不创建或复制 artifact 文件。
- 不转发新的子事件类型、不实现 TUI 展示、不引入并行子 Agent 或多 artifact 聚合。

## Decisions

### 1. 在 core 定义四类小型不可变值对象

新增 `SubagentFinding`、`SubagentEvidence`、`SubagentUsage` 和 `SubagentArtifact`，并将它们作为 `SubagentResult` 的尾部可选字段：

- finding 包含有界结论文本及其 `evidence_ids`；当前运行器不从自由文本自动生成 finding。
- evidence 包含稳定的 `evidence_id`、工具来源、可选 locator、短摘要/摘录、输出完整性和 continuation。
- usage 固定为 `input_tokens`、`output_tokens`、`reasoning_tokens`、`cached_tokens` 四个非负整数，避免 core 依赖 session 的 `UsageStats`。
- artifact 只包含有界 `ref`、`kind` 和 `label`，最多返回一个；ref 可以来自工具已经提供的 `artifact_ref` 或 `artifact_path`。

所有值对象使用 frozen dataclass，并提供 `to_dict()`；`SubagentResult` 也提供 detached 的字典表示。结果字段追加在现有字段之后，省略时分别归一为空 tuple 或 `None`，避免破坏旧的 positional/keyword 构造。

备选方案是把结果定义为任意 `dict`。该方案短期改动少，但会让父级、TUI 和持久化各自解释字段，无法在入口统一校验边界，因此不采用。

### 2. 在结果契约入口统一执行边界校验

使用固定常量限制最多 16 个 findings、32 条 evidence 和 1 个 artifact；摘要最多 16000 字符，finding 文本最多 2000 字符，evidence source/locator/continuation 最多 512 字符、evidence summary 最多 2000 字符、excerpt 最多 1200 字符，artifact ref 最多 512 字符、label 最多 200 字符。evidence id 必须唯一，finding 引用必须指向同一结果中的 evidence；token 字段必须是非负且不能是 bool 的整数。

边界失败统一使用 `SubagentContractError(code="invalid_result")`。不在 `ToolResult` 或 TUI 再做第二套结构解析；应用层只负责按预算截断候选摘录，契约层负责拒绝任何绕过提取器的越界值。

### 3. 从子历史的工具元数据生成 evidence，而不是复制 transcript

组合层在子运行完成后按历史顺序配对 assistant 的 `ToolCall` 与 tool message，通过调用 id 找到工具名。仅当 tool message 有 `ToolOutputMetadata` 时才生成 evidence；locator 优先使用 path 和 range，完整性直接沿用元数据，excerpt 使用有界的工具结果内容。完整工具消息、父历史、内部任务对象和未结构化 prompt 不进入结果。

artifact 只从 `artifact_ref` 或 `artifact_path` 读取，按首次出现顺序取一个，避免把工作区文件列表误当成 artifact。普通 `path` 只作为 evidence locator，不自动升级为 artifact。

### 4. 使用公开运行用量边界聚合 token

在 `AgentSession` 增加只读的 `run_usage` 视图，暴露当前/最近一次运行由 `SessionRuntime` 累计的 `UsageStats`；组合层首先读取该视图，兼容性回退到 `last_actual_usage`、`usage` 或测试 double 提供的同形对象。这样多轮子运行不会只返回最后一次模型请求的用量，同时不把持久化层类型导入 core。

### 5. ToolResult 维持现有文本兼容，并平行暴露结构化 details

`delegate_result.tool_result` 保持 content 为有限摘要或失败文本，继续设置现有 status/error/cleanup 字段；在 details 顶层追加 `summary`、`findings`、`evidence`、`usage` 和 `artifact`。缺失值使用空列表或 `None`，避免 JSON 消费者处理自定义 dataclass。失败结果同样保留已收集的结构化字段，但不会被标记为成功。

备选方案是把 JSON 编码拼接进 content。该方案会迫使模型重新解析文本、增加上下文 token，并且破坏既有摘要展示，因此不采用。

## Risks / Trade-offs

- [自由文本中可能存在真实但未结构化的发现] → 明确返回空 findings，不做不可靠猜测；后续可通过专门的模型输出契约增加显式 findings。
- [工具结果摘录可能包含敏感工作区内容] → 只保留现有工具已经交给子模型的短摘录，并继承工具输出的有界大小；不扩展权限、不读取新文件、不复制完整输出。
- [旧测试 double 没有 `run_usage`] → 提供多级同形属性回退，并用实际 AgentSession 与最小 fake session 分别覆盖。
- [多个工具结果产生过多证据] → 按历史顺序限制 32 条，保留前面的稳定观察并在结果契约中拒绝调用方自行构造的超限数组。
- [artifact_path 是绝对路径，跨机器不可用] → 将其作为现有工具产出的引用而非可恢复保证；V5-08 再定义持久化和恢复语义。

## Migration Plan

1. 先新增 core 值对象、公共导出和契约测试，再接入子结果提取与 ToolResult 映射。
2. 运行 unit/contract、app 集成、全量测试、Ruff、规模检查、OpenSpec 校验和构建。
3. 归档时将 delta 同步到 `openspec/specs/subagent-runtime/spec.md`，并在 V5.05 文档记录验证证据。
4. 回滚只需恢复本阶段提交；旧调用方省略新增字段仍可按原摘要/失败映射运行。

## Open Questions

无。V5-06 可以在不改变本阶段契约的前提下决定如何把这些字段投影到事件和 TUI。
