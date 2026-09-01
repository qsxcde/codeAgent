## Context

当前子 Agent 由 `SerialSubagentRunner` 创建独立 Session，Session 本身已经为事件填充 `session_id`、`run_id` 和 run 内 `sequence`。`subscribe_child()` 会把子事件交给 `DelegateTool` 的 `on_update`，但通用工具调用层会把它们包装成父级 `tool_progress` 的 payload，因而父级消费者看不到一等的委派事件；同时 `SubagentState` 只在 core 中独立存在，真实 runner 没有使用它作为终态线性化点。

本变更只处理事件契约、运行器转发和诊断，不改变 TUI 展示、持久化格式或并行调度。设计需要同时满足两套序列：子 Session 原生序列用于重建一个 child run 的局部顺序，父 Session 接收序列用于描述跨父子事件的到达顺序。

## Goals / Non-Goals

**Goals:**

- 让已接受委派的排队、启动、进度和终态事件以顶层事件进入父级事件流。
- 让每个事件可通过 delegation、父子 run、attempt、depth 和状态字段定位，并同时保留父级接收序列与子级原生序列。
- 将 `SubagentState` 接入 runner 的状态转换和唯一终态发布，覆盖取消、超时、预算失败和清理不确定。
- 限制事件负载为状态和操作摘要，隔离观察者异常与迟到事件。
- 保持普通单 Agent 事件和既有通用工具进度回调兼容，为 V5-07 的 TUI 投影提供稳定输入。

**Non-Goals:**

- 不在本变更中绘制委派块、展开子进度或修改 TUI transcript。
- 不把子 Agent 的完整文本增量、消息对象、提示词、工具输出或内部任务对象转发给父级。
- 不实现并行子 Agent、后台 handle、跨进程恢复或委派结果持久化。

## Decisions

### 1. 使用专用 Subagent 事件类型，而不是继续伪装为工具进度

新增 `SUBAGENT_QUEUED`、`SUBAGENT_STARTED`、`SUBAGENT_PROGRESS` 和 `SUBAGENT_FINISHED` 四种事件类型。它们仍使用现有 `AgentEvent` envelope，以复用 EventBus、Session 的 run 关联和旧消费者的未知事件兼容能力。

`SUBAGENT_PROGRESS` 的 payload 只保留事件种类、阶段、工具名/操作标识、状态、耗时和有限诊断；不携带原始子 `AgentEvent`。`SUBAGENT_FINISHED` 的 payload 使用已经受 V5-05 限制的结果字典，避免重复引入 transcript 通道。专用类型让当前 TUI 忽略这些事件，V5-07 可以按 delegation_id 建立独立投影。

备选方案是把子事件继续放入 `TOOL_PROGRESS`，或直接转发原始子事件。前者让消费者必须识别嵌套结构，后者会让父级 TUI 把子文本当成父回答并可能泄漏无界负载，均不采用。

### 2. 事件的运行归属和两套序列分开

排队事件在尚无 child_run_id 时使用父 run_id；子 Session 创建后，启动、进度和终态 envelope 使用真实 child run_id，同时携带 parent_run_id。父级接收顺序放在 `parent_sequence`，由父 runtime 在允许跨 run 转发时分配；子 Session 原生 `sequence` 保留为 `child_sequence`，不被父级序列重写。为了兼容现有 metadata-only 消费者，关联字段同时写入 AgentEvent 类型化字段和 metadata。

父 runtime 对具备 Subagent 专用类型且 child run 不同的事件只做关联/序列归一和转发，不调用父运行的阶段归约；这样子事件不会把父运行错误地推进到模型等待、工具执行或终态。普通事件仍沿用原有 run_id 过滤规则。

### 3. 让通用工具回调识别结构化事件

`core` 的工具调用桥接保留现有任意 update 的 `TOOL_EXECUTION_UPDATE` 包装行为；当 update 已经是专用 Subagent `AgentEvent` 时，直接发送该事件。这样事件仍经过父 Agent 的 emit、Session runtime 和父 EventBus，但不会再套一层 `tool_progress`。非 Subagent runner 和普通工具 update 的行为不变。

### 4. 以 SubagentState 作为唯一终态线性化点

`ActiveDelegation` 持有一个对应请求的状态对象。接受请求时进入 `queued`，取得串行槽后进入 `starting`，子 Session 建立后进入 `running`；确认事件可以进入/离开 `waiting_confirmation`，取消或超时经过 `cancelling`。成功、启动/执行失败、预算失败、超时和父级取消分别提交匹配的终态结果。

终态结果完成清理归一后才调用状态的终态提交保护，并在保护通过时发布一次 `SUBAGENT_FINISHED`。重复相同结果不重复发布，冲突结果记入诊断；预算失败可以直接从运行状态提交 `failed + budget_exceeded`，不把取消收尾误报成 `cancelled`。

备选方案是以 `active` 字典是否存在或 `result is None` 判断终态。那样无法保护完成/取消竞态，也无法复用 core 已验证的非法转换和 attempt 身份约束，因此不采用。

### 5. 迟到事件采用关闭闸门并保留诊断

当 runner 已得到终态候选结果或开始关闭子 Session 时，停止向父级转发新的子过程事件；回调入口先检查事件闸门和状态终态，再决定丢弃并追加截断的 `late_event` 诊断。订阅取消、异步观察任务和 Session 关闭仍使用现有有界收尾窗口，诊断沿用 V5-04/V5-05 的数量与字符上限。

观察者同步异常和异步异常只影响诊断，不传播为子 Agent 主结果失败。终态事件自身的发布通过同一个回调路径执行，失败时仍保留已经提交的结果和失败诊断，不能再次尝试发布第二个终态。

## Risks / Trade-offs

- **[风险]** 父 EventBus 收到 child run_id 的事件可能被旧消费者按单 run 过滤。→ **缓解**：使用专用事件类型和 parent_run_id/parent_sequence；普通事件消费者无需订阅 Subagent 类型，兼容测试固定 metadata-only 行为。
- **[风险]** 跨父子事件到达顺序与各自原生序列含义不同。→ **缓解**：不覆盖 child sequence，额外写入 parent_sequence，并明确两个序列的命名空间。
- **[风险]** 终态事件发布失败导致 UI 看不到完成状态。→ **缓解**：先提交不可逆状态和结果，再记录回调诊断；V5-07 可从后续结果/工具终态恢复显示，不重新发布冲突事件。
- **[风险]** 仅保留摘要可能不足以诊断复杂子运行。→ **缓解**：携带阶段、工具操作标识、reason code、cleanup 状态和有限错误文本；完整 transcript 和详细历史留给后续显式调试能力。
- **[风险]** 事件处理新增分支破坏父 Session 阶段。→ **缓解**：专用 Subagent 事件只做父级接收序列和转发，不参与父 `RunPhase` 归约，并加入真实 FakeClient 事件回归。

## Migration Plan

1. 扩展 core 事件类型及关联字段，补充父/子序列和旧消费者兼容测试。
2. 在工具调用桥接、Session runtime 和 Subagent runner 中接入专用事件 envelope、状态机和终态发布保护。
3. 增加排队/启动/进度/终态、乱序与迟到、取消/超时/预算、观察者异常和清理不确定的单元及集成测试。
4. 通过 OpenSpec、Ruff、规模检查、分层测试和全量离线测试后提交；不需要 JSONL 迁移。若回滚，删除专用事件转发并保留现有嵌套工具进度兼容路径即可。
