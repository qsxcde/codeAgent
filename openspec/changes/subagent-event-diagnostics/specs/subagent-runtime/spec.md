## ADDED Requirements

### Requirement: 父子事件转发与运行诊断

对于已经接受的 Subagent 委派，运行器 SHALL 向父级 Session EventBus 发布可直接消费的 `SUBAGENT_QUEUED`、`SUBAGENT_STARTED`、`SUBAGENT_PROGRESS` 和 `SUBAGENT_FINISHED` 事件。事件 SHALL 保留父子运行关联、attempt、深度、子阶段、稳定 `subagent_status`、有界诊断和父/子序列；子事件不得继续作为完整 `AgentEvent` 嵌套在通用 `tool_progress` payload 中。运行器 SHALL 使用单一的生命周期提交点发布一次 `SUBAGENT_FINISHED`，完成、失败、预算耗尽、超时和取消之间的竞态不得产生重复或冲突终态。

子事件回调失败、子运行在终态后产生的迟到事件以及无法确认清理的情况 SHALL 被转换为固定上限内的诊断；这些诊断不得改变已提交结果、重新激活子运行或覆盖父运行状态。没有 Subagent 委派的普通 Session 事件和未装配 runner 的 Agent 行为 SHALL 保持原有顺序与语义。

#### Scenario: 排队和启动事件可定位

- **WHEN** 父 Agent 接受合法委派并等待串行执行槽，随后创建独立子运行
- **THEN** 父级 EventBus 先后收到可按 `delegation_id` 定位的排队/启动事件；child_run_id 在可用后出现，父运行标识不被子运行覆盖

#### Scenario: 子运行进度作为顶层事件转发

- **WHEN** 子 Agent 进入模型等待、工具执行、确认等待或取消收尾阶段
- **THEN** 父级 EventBus 收到顶层 `SUBAGENT_PROGRESS`，带有子阶段、状态、child_run_id、子序列和父级接收序列；事件不会把完整子消息或工具输出写入父 transcript

#### Scenario: 正常完成只发布一个终态

- **WHEN** 子 Agent 成功结束且资源清理已确认
- **THEN** 父级 EventBus 恰好收到一个 `SUBAGENT_FINISHED`，其状态为 `completed`，并与返回的 delegation_id、child_run_id 和结果摘要一致

#### Scenario: 失败、超时和取消保留可操作诊断

- **WHEN** 子 Agent 启动失败、执行失败、预算耗尽、墙钟超时或收到父级取消
- **THEN** 终态事件分别保留稳定状态/reason code、阶段、cleanup 诊断和有限错误信息，且不会被后续普通完成事件改写为成功

#### Scenario: 迟到事件不会覆盖终态

- **WHEN** `SUBAGENT_FINISHED` 已发布后，或运行器已经开始关闭订阅后，子事件回调再次到达
- **THEN** 运行器忽略该事件或将其记为有界 late-event 诊断，不再转发过程事件、不重新打开活动委派表，也不发布第二个终态

#### Scenario: 事件观察失败不破坏主结果

- **WHEN** 父级事件消费者或异步事件观察回调抛出异常
- **THEN** 运行器隔离该异常并保留有限诊断，子 Agent 的成功/失败/取消结果和资源清理仍按原流程完成

#### Scenario: 清理不确定在事件中保持诚实

- **WHEN** 取消、超时或关闭后无法确认子模型、工具、事件观察任务或子进程已经停止
- **THEN** 唯一终态事件携带 `cleanup_uncertain=true` 和截断诊断，不能发布已确认清理或重新激活运行的事件

#### Scenario: 普通单 Agent 事件不受影响

- **WHEN** Session 没有执行 Subagent 委派，或 AgentLoopConfig 未装配 runner
- **THEN** 既有事件类型、run_id、序列和工具进度行为保持不变，不产生空的 Subagent 事件
