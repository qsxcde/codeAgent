## Purpose

为父会话保存可恢复、可追踪且严格有界的 Subagent 委派事实，同时隔离临时子会话 transcript，避免重启后出现幽灵运行、重复终态或虚假的成功状态。

## ADDED Requirements

### Requirement: 父会话委派运行记录

父会话 SHALL 为已接受的 Subagent 委派追加独立的运行记录，至少保留有界的任务标签、profile、delegation_id、parent_run_id、child_run_id（如可用）、attempt_id（如可用）、状态、阶段、结果摘要和必要诊断。记录不得包含完整 task/context、子消息列表、内部任务对象或无界工具输出；记录追加不得改变普通消息、标题和最近活动时间语义。

#### Scenario: 委派生命周期可追踪

- **WHEN** 父 Agent 接受委派并产生排队、启动、关键进度或终态事件
- **THEN** 父会话记录能够按 `delegation_id` 关联该委派，记录最新可用的状态与子运行身份，并保留有界的终态摘要和诊断

#### Scenario: 记录不复制子 transcript

- **WHEN** 子 Agent 产生消息、工具输出或内部事件
- **THEN** 父会话只追加有限运行事实，不把子 transcript、完整 prompt/context 或无界输出写入父会话记录

#### Scenario: 记录不污染会话列表

- **WHEN** 父会话包含 Subagent 运行记录或临时子运行存在
- **THEN** 普通会话列表、标题派生、最近活动排序和 `/sessions` 候选仍只基于父会话，不将子运行显示为独立普通会话

### Requirement: 委派记录终态幂等

同一 `delegation_id` SHALL 只保留一个有效终态；读取或追加记录时，终态不得被迟到的过程记录、重复终态或冲突终态回退或覆盖。记录写入失败 SHALL 不改变父 Agent 的运行结果，并 SHALL 通过有限诊断暴露，而不是阻塞或伪造成功记录。

#### Scenario: 重复终态不产生重复结果

- **WHEN** 同一委派的终态事件被重复到达，或恢复时 JSONL 含有重复终态记录
- **THEN** 调用方只看到一个稳定终态及其首次有效结果，不产生重复 Subagent 块或错误成功状态

#### Scenario: 迟到过程记录不回退

- **WHEN** 已记录 `completed`、`failed`、`timed_out`、`cancelled`、`rejected` 终态后又读取或接收过程状态
- **THEN** 已记录终态、摘要、reason code 和清理事实保持不变

### Requirement: 重启后的未完成委派

恢复父会话时，最新记录仍处于 `queued`、`starting`、`running`、`waiting_confirmation` 或 `cancelling` 的委派 SHALL 被转换为明确的 `abandoned`/`process_restarted` 不可恢复结果。恢复 SHALL 不重新创建子 Session、不报告其仍在运行，也不得把该记录转换为成功终态；无法确认清理时 SHALL 保留诚实的清理不确定诊断。

#### Scenario: 进程重启标记活动委派

- **WHEN** JSONL 最后一个委派记录是非终态，且新进程加载父会话
- **THEN** 恢复结果显示该委派不可恢复或 `abandoned`，带有稳定的 `process_restarted` 诊断，活动委派集合为空

#### Scenario: 已完成委派正常恢复

- **WHEN** JSONL 已存在有效的 Subagent 终态记录，且父会话重新加载
- **THEN** 恢复方保留该委派的终态、结果摘要、关联 ID、结构化统计和必要诊断，且不重复追加或重新执行子任务

#### Scenario: 旧会话没有委派记录

- **WHEN** 旧 JSONL 只有 header、消息、元数据、usage 或压缩记录而没有 Subagent 字段
- **THEN** 会话照常恢复，委派记录为空，不产生兼容性错误或虚构的子任务

### Requirement: 恢复展示使用有限投影

恢复后的父会话 SHALL 将有效终态或 abandoned 委派记录投影为独立、默认折叠且有界的 Subagent 展示块；展示 SHALL 保留状态、阶段、耗时/身份、摘要和诊断，但不得把记录转换为普通 assistant/tool 消息，也不得因为子 transcript 的物理增长重新渲染全部父历史。

#### Scenario: 恢复后仍可看到委派结果

- **WHEN** 用户打开包含已完成或失败委派记录的父会话
- **THEN** TUI 能看到对应的独立委派块及其状态和结果摘要，父普通消息历史保持原有顺序

#### Scenario: abandoned 不显示为运行中

- **WHEN** 用户打开含有进程重启遗留非终态记录的父会话
- **THEN** 展示明确标为不可恢复/已中断，并显示 `process_restarted`，不显示运行中计数或活动动画
