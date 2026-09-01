## Context

当前 `SubagentRequest` 已经包含可选 `SubagentBudget`，`AgentSession` 也提供了取消、确认队列和工具运行时清理能力，但这些能力尚未由串行 runner 统一编排。子会话工厂可以控制递归轮数，事件订阅可以观察会话阶段，工具运行时可以取消活动操作；组合根应在这些既有边界上增加 Subagent 专属的策略，而不把 Session 或具体工具依赖带入 `core`。

## Goals / Non-Goals

**Goals:**

- 为请求建立可解释、可测试且向后兼容的有效预算；
- 在队列、启动、模型、工具和确认等待期间统一执行墙钟截止时间；
- 让预算耗尽、超时和父级取消走不同的结构化结果；
- 在正常结束、异常、取消和超时路径都完成有界收尾，并诚实暴露清理不确定性；
- 保持单 runner 串行执行、父子上下文隔离和现有单 Agent 行为不变。

**Non-Goals:**

- 不在本变更中实现并行子 Agent、持久化 transcript、证据抽取或 TUI 展示；
- 不改变 `RunPhase` 的公共枚举，也不为每种 Subagent 预算错误增加新的 Session 状态；
- 不允许子 Agent 通过 budget 提升 profile、工作区或工具权限；
- 不增加第三方依赖或修改用户会话的持久化格式。

## Decisions

### 1. 在 app/composition/subagent 集中解析有效预算

新增轻量的 Subagent budget policy 模块，定义默认值、硬上限和父运行子任务上限，并将旧的 `None` 字段解析为有效正数。`DelegateTool` 在模型输入边界校验一次，`SerialSubagentRunner` 对直接调用的 `SubagentRequest` 再校验一次。这样既保持 `core` 契约的 provider-neutral，又避免绕过工具 schema 直接调用 runner。

本变更固定以下策略：

| 项目 | 默认值 | 单次允许的硬上限 |
|---|---:|---:|
| 父运行已接受子任务数 | 4 | 4 |
| 子运行模型轮数 | 8 | 16 |
| 子运行工具调用数 | 32 | 64 |
| 子运行墙钟时间 | 120 秒 | 300 秒 |
| 返回摘要字符数 | 8000 | 16000 |

备选方案是把这些字段暴露为全局配置或只在 Session 中限制。全局配置无法表达一次委派的边界，只在 Session 中限制又不能保护直接使用 runner 的调用，因此选择应用组合层的请求策略。

### 2. 轮数使用现有 recursion_limit，工具调用使用子事件计数

创建子 Session 时将有效 `max_turns` 传给既有 Agent 循环的 `recursion_limit`，保持轮次语义与父 Agent 一致。runner 通过子 Session 事件订阅统计去重后的 `TOOL_QUEUED` 和 `TURN_START`；达到工具调用上限时立即请求子 Session 中止，避免继续启动后续工具。达到轮数上限由核心循环的 `RecursionLimitError` 兜底，runner 将该错误归一化为 `failed + budget_exceeded`。

备选方案是在 core `AgentLoopConfig` 增加专用预算回调。它会扩大 provider-neutral 核心接口，并且工具批次已经开始后才容易发现越界；本阶段使用已有递归入口和稳定事件，减少跨层改动。

### 3. 墙钟超时覆盖队列和整个子运行

runner 在接受请求时计算自己的墙钟截止时间，把获取串行锁、子工厂创建、子 `run()`、模型调用、工具执行和确认等待放在同一个超时边界内。等待子 task 时使用 shield，超时只先唤醒 runner 自己，再通过 Session 的取消入口停止子运行，避免 `wait_for` 直接丢失子 Session 的收尾机会。超时结果固定为 `TIMED_OUT / TIMEOUT`，不复用父级取消结果。

备选方案只对 `child.run()` 设置 timeout，会让排队时间无限增长；只取消 task 而不调用 Session 取消入口，则可能遗留确认请求、工具运行时或外部资源，因此不采用。

### 4. 取消原因由活动委派保存，不依赖异常文本

活动记录保存 `parent_cancelled`、`timeout` 和 `budget_exceeded` 的内部原因。`runner.cancel()` 只设置父级取消并定位对应活动项；事件计数超限设置预算取消；墙钟边界设置超时取消。child 抛出的异常文本只作为诊断，终态映射优先使用保存的原因和既有 `last_failure` 错误码。

### 5. 将清理设计为有界的两阶段流程

第一阶段请求 Session `cancel_and_wait(timeout=...)`，若没有该接口则调用 `abort()` 并等待已知 child task；第二阶段取消事件观察任务并调用 `close()`。每个步骤共享一个有限的清理截止时间，超时、抛错或 task 仍然挂起都会记录有限诊断并设置 `cleanup_uncertain`。结果构造延后到清理之后，再将清理事实写入 `SubagentResult`；`SubagentResult` 增加向后兼容的结果级 `cleanup_uncertain` 字段，失败结果同时设置其 `SubagentFailure.cleanup_uncertain`。

完成但 close 失败的子运行可以保留逻辑上的 `completed`，但其 ToolResult 必须是 `cleanup_confirmed=False`，让用户和上层知道结论已产生而资源收尾不确定；取消、超时和失败结果也沿用相同诊断字段。

备选方案是把 close 异常静默追加 diagnostics，或把所有 close 异常升级为执行失败。前者会误报清理成功，后者丢失“任务已完成但收尾失败”的事实，因此选择显式结果级诊断。

### 6. 父运行子任务配额绑定到执行期 DelegateTool 副本

`AgentSession` 每次执行都会为工具绑定当前 `parent_run_id`。`DelegateTool.bind_parent_run_id()` 返回带独立计数器和异步锁的执行副本，最多接受 4 个有效委派；计数器不会写入共享 Session 或跨父运行泄漏。并发工具批次下先在该锁内预留配额，再调用 runner，超额请求不创建子 Session。

## Risks / Trade-offs

- [Risk] 某个外部工具或自定义 Session 忽略取消并长期运行 → 使用有限清理窗口返回 `cleanup_uncertain`，同时保留活动 task 的诊断；内置工具继续由现有 ToolExecutionRuntime 负责取消。
- [Risk] 事件订阅者丢失 `TOOL_QUEUED` 事件会使工具计数不可见 → 子工厂仍强制使用有效 `max_turns`，runner 对直接子 Session 保持保守的活动取消路径；集成测试固定真实 AgentSession 的事件形态。
- [Risk] 父运行配额按执行副本保存，跨 `AgentSession.run()` 不共享 → 这是“单次父运行”语义的要求；后续若需要跨运行额度，应新增独立调度器，不隐式改变本变更。
- [Risk] 120 秒默认墙钟会改变此前无限等待的子任务体验 → 默认值与 300 秒硬上限写入 schema、诊断和文档；父级仍可按任务显式请求更短或更长但受限的 budget。
- [Risk] cleanup 不确定时仍可能有后台非合作 task → 不伪造确认状态，并在结果/诊断中暴露；后续资源隔离变更可基于该信号增加 abandoned 记录，而本变更不制造虚假的终态。

## Migration Plan

1. 先加入预算策略、请求解析和回归测试，再修改 runner 与子 Session 工厂。
2. 未提供 `budget` 的旧 `delegate` 调用自动使用固定默认值，不要求用户迁移 prompt 或配置。
3. 在所有窄测试、分层测试、OpenSpec strict validation 和构建通过后，将 V5-04 标记完成并同步主规格。
4. 若需要回滚，只需回滚本变更提交；旧的无预算请求契约仍可反序列化，父 Agent 未装配 runner 时行为不变。

## Open Questions

无。预算数值、错误码、超时覆盖范围和清理不确定语义已在本变更中固定。
