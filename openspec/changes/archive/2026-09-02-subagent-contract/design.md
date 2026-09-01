## Context

当前 `core` 已通过 `AgentTool`、`AgentEvent` 和 ReAct 循环提供单 Agent 的 provider-neutral 运行能力。`session/runtime/state.py` 中的 `RunPhase` 同时表达模型等待、工具执行、持久化收尾和会话终态；它适合一个 SessionRuntime，不适合作为父子委派的调度状态。当前没有 Subagent 请求、结果或运行器端口。

本设计遵循 `core` 的既有边界：不导入 `ai`、`tools`、`session`、`config`，不把可变 `AgentContext`、具体 `AgentSession` 或外部任务对象放进核心契约。

## Goals / Non-Goals

**Goals:**

- 冻结可由 FakeRunner 单独验证的委派请求、结果和状态转换契约。
- 把委派生命周期与子 Agent 内部的 `RunPhase`、父 Session 的提交/收尾生命周期分离。
- 统一终态唯一性、取消/超时收尾和稳定 reason code 的语义。
- 为父子事件提供不破坏既有单 Agent 消费者的关联字段。
- 为后续 `app/composition/subagent/` 运行器、上下文策略和 TUI 观测保留稳定扩展边界。

**Non-Goals:**

- 不创建真实的子 Agent、`AgentSession` 或 SessionManager 调度逻辑。
- 不实现 `delegate` 工具、模型/工具 profile、上下文选择、持久化或 TUI 展示。
- 不实现多个 Subagent 并发调度、跨进程 Worker 或活动子运行恢复。
- 不在本阶段定义完整的 findings、evidence、artifact 和 transcript 传输格式；这些由后续结构化结果变更扩展。

## Decisions

### 1. 使用独立的 Subagent 状态，而不是复用 `RunPhase`

新增一个只描述委派生命周期的状态模型。状态从 `created` 开始，经过排队和启动，进入运行或确认等待，取消和超时通过 `cancelling` 收尾，最后进入不可逆终态。

```text
CREATED -> QUEUED -> STARTING -> RUNNING
   │         │          │          ├─> WAITING_CONFIRMATION -> RUNNING
   │         │          ├─> FAILED │
   │         │          └─> TIMED_OUT
   │         └─> CANCELLED          ├─> COMPLETED
   └─> REJECTED                      ├─> FAILED
                                    └─> CANCELLING -> CANCELLED / TIMED_OUT
```

`RunPhase` 仍由每个独立子 Session 管理：子 Agent 的 `model_wait`、`tool_running` 等作为子运行进度，不提升为父级委派状态。这样父 Agent 的 `tool_running(delegate)` 与子 Agent 的内部阶段可以并行存在。

备选方案是把 Subagent 状态直接映射到 `RunPhase`。该方案会把 `FINALIZING`、提交状态和委派调度混在一起，也无法表达“已排队但尚未创建子运行”，因此不采用。

### 2. 请求、结果和状态分离

请求和结果使用不可变值对象，状态使用一个只保存生命周期事实的可变状态对象：

- `SubagentRequest`：`delegation_id`、`parent_run_id`、任务、profile、`depth`、有效 `max_depth`、预算，以及可选的不可变上下文事实。
- `SubagentBudget`：轮数、工具数、墙钟时间和输出上限等有界数值；未设置的限制使用 `None`，所有设置值必须为正数。
- `SubagentFailure`：`reason_code`、失败阶段、用户可读摘要、`retryable`、`side_effect_state` 和 `cleanup_uncertain`；不携带原始异常对象、任务对象或 provider 响应。
- `SubagentResult`：`delegation_id`、`child_run_id`、`attempt_id`、终态、有限摘要和失败诊断。只有终态才能构造结果。
- `SubagentState`：保存当前状态、取消请求、子运行标识、尝试标识、序列号和已提交的终态结果。

阶段 1 只冻结结果 envelope 和终态语义，后续可以以默认值方式加入 findings、evidence、usage 和 artifact 引用，避免在核心契约中提前绑定具体输出格式。

备选方案是直接把 `SubagentResult` 设计为 `ToolResult` 的别名。该方案会丢失子运行身份、尝试和生命周期诊断，也会让父工具结果与子任务结果无法分别演进，因此只在应用组合层提供显式转换。

### 3. 运行器采用同步等待的异步端口

阶段 1 的 `SubagentRunner` 提供 `execute(request, on_event=None) -> SubagentResult` 和 `cancel(delegation_id) -> bool`。`execute` 只返回终态结果；事件回调只传递 provider-neutral 的 `AgentEvent`，不暴露子 Agent 内部对象。

父 Agent 的 `delegate` 工具在后续 MVP 中等待 `execute` 完成，这与当前工具批次模型兼容，并保持单次委派串行。需要后台查看、暂停或多子任务调度时，再增加独立的 handle/scheduler 设计，不把这些复杂度提前塞进核心端口。

运行器是状态机的驱动者，但不能绕过状态机直接发布终态。每个 `delegation_id` 由单一协调者串行化状态提交；同一终态的重复回放可幂等处理，冲突终态被拒绝。取消和完成同时到达时，以先成功提交终态的一方为准；超时一旦提交，不得被普通执行失败覆盖。

### 4. 稳定 reason code 与顶层状态正交

顶层状态只表达生命周期，reason code 表达原因。推荐的最小代码集合为：

| 场景 | 状态 | reason code |
|---|---|---|
| 请求无效 | `rejected` | `invalid_request` |
| 深度超限 | `rejected` | `depth_exceeded` |
| profile 不允许 | `rejected` | `permission_denied` |
| 启动失败 | `failed` | `startup_failed` |
| 模型/工具失败 | `failed` | `execution_failed` |
| 预算耗尽 | `failed` | `budget_exceeded` |
| 墙钟超时 | `timed_out` | `timeout` |
| 父级取消 | `cancelled` | `parent_cancelled` |
| 确认中止 | `cancelled` | `confirmation_rejected` |

具体模型或工具的错误可以在 `execution_failed` 下携带受控的扩展代码，但不得让每一种底层异常成为新的顶层状态。`cleanup_uncertain` 是独立诊断，适用于取消和超时结果。

备选方案是为 `budget_exhausted`、`permission_denied` 和 `cleanup_uncertain` 各增加生命周期状态。这样会使状态矩阵迅速膨胀，并让消费者无法区分“运行阶段”和“失败原因”，因此不采用。

### 5. 父子事件使用显式关联字段

在 `AgentEvent` 上增加可选的类型化快捷字段，并继续保留 metadata 兼容读取：

- `delegation_id`
- `parent_run_id`
- `child_run_id`
- `attempt_id`
- `depth`
- `subagent_status`
- `child_phase`

事件的 `run_id` 始终表示事件所属运行：父级委派事件使用父 `run_id`，子 Agent 原生事件使用子 `run_id`。阶段 1 只定义字段和一致性测试，不新增事件路由或 TUI 事件类型；V5-06 再定义委派事件的发布、迟到事件处理和展示语义。

备选方案是只把关联信息塞进自由格式 metadata。该方案延续旧消费者兼容性，但容易出现字段拼写和来源不一致；采用类型化字段加 metadata fallback，新增生产者同时填充两者，旧事件仍可只使用 metadata。

### 6. 保持公共门面和 core 依赖边界

新契约从 `codeagent.core` 公共门面导出，并在包结构测试中固定路径和对象身份。错误类型放在 core contracts 中，不复用位于 session 的 `RuntimeFailure`，避免反向依赖；后续可以在应用层把两者转换为各自的事件诊断。

## Risks / Trade-offs

- **[风险]** 新状态机与 `RunState` 存在概念重复。→ **缓解**：明确前者只描述委派调度，后者只描述单个 Session Runtime，并用适配层桥接，不共享枚举。
- **[风险]** AgentEvent 的类型化字段与 metadata 可能不一致。→ **缓解**：规定生产者同时写入两种表示，读取时类型化字段优先，并添加 metadata-only 和 typed-only 回归测试。
- **[风险]** 取消、超时和完成存在竞态。→ **缓解**：每个委派只允许一个状态提交者，终态转换作为唯一线性化点；重复相同终态幂等，冲突终态拒绝。
- **[风险]** 结果 envelope 后续扩展导致接口不兼容。→ **缓解**：阶段 1 只冻结身份、状态、摘要和失败字段；后续结构化结果字段使用不可变集合和默认值追加。
- **[风险]** 开发者把具体 Session 或 provider 类型塞入 core。→ **缓解**：保留现有 import-boundary 和规模测试，在契约测试中扫描禁止依赖。

## Migration Plan

1. 先增加 core 契约、状态机、错误类型、事件关联字段和公共导出；不改变现有单 Agent 执行路径。
2. 增加 FakeRunner、状态转换、结果归一化、事件关联和 import boundary 测试。
3. 通过 OpenSpec、Ruff、相关单元/契约测试后，后续变更再在 `app/composition/subagent/` 接入真实运行器。
4. 如需回滚，删除新增契约和可选事件字段即可；既有单 Agent 事件和 `RunPhase` 不需要数据迁移。
