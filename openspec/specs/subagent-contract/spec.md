# subagent-contract Specification

## Purpose

为父 Agent 委派独立子 Agent 提供稳定、可验证且与具体模型、工具和会话实现解耦的请求、状态、结果及父子运行关联契约。

## Requirements

### Requirement: 委派请求与终态结果

系统 SHALL 为一次子 Agent 委派保留稳定的 `delegation_id`、`parent_run_id`、任务描述、能力 profile、嵌套深度和有效预算。委派结果 SHALL 保留请求归属，并以一个终态状态、可选的有界摘要和结构化失败信息表示结果；结果不得要求调用方解析异常文本来判断执行状态。

#### Scenario: 有效请求进入排队状态

- **WHEN** 调用方提交包含非空委派标识、父运行标识、任务描述和合法预算的请求
- **THEN** 系统接受请求并将其置于 `queued` 状态，且不改变父运行的上下文或历史消息

#### Scenario: 请求结构校验失败

- **WHEN** 委派标识、父运行标识、任务描述、深度或预算不满足契约约束
- **THEN** 系统生成 `rejected` 结果，并携带稳定的 `invalid_request` reason code，且不创建子运行

#### Scenario: 深度或权限校验失败

- **WHEN** 请求的有效深度超过限制，或请求的 profile 未被允许
- **THEN** 系统生成 `rejected` 结果，并分别使用 `depth_exceeded` 或 `permission_denied` reason code，且不产生子 Agent 副作用

#### Scenario: 终态结果保留委派归属

- **WHEN** 子 Agent 以成功、失败、超时、取消或拒绝结束
- **THEN** 返回结果中的 `delegation_id` 与请求一致，且 `child_run_id`、`attempt_id` 和失败诊断在可用时保持可追踪

### Requirement: 委派生命周期状态

系统 SHALL 使用独立于会话 `RunPhase` 的委派状态表达 `created`、`queued`、`starting`、`running`、`waiting_confirmation`、`cancelling`、`completed`、`failed`、`timed_out`、`cancelled` 和 `rejected`。`completed`、`failed`、`timed_out`、`cancelled` 与 `rejected` SHALL 是不可逆终态；任何终态之后不得转换为过程状态或另一个终态。

#### Scenario: 正常生命周期转换

- **WHEN** 合法请求获得执行资源，子 Agent 启动并正常完成
- **THEN** 委派状态依次可以从 `created` 经 `queued`、`starting`、`running` 转换为 `completed`

#### Scenario: 排队期间取消

- **WHEN** 委派仍处于 `queued` 且父级请求取消
- **THEN** 委派直接进入 `cancelled`，不创建或启动子 Agent

#### Scenario: 执行期间等待确认

- **WHEN** 子 Agent 的工具操作需要上层确认
- **THEN** 委派进入 `waiting_confirmation`；批准后回到 `running`，中止后进入 `cancelling`

#### Scenario: 超时与取消经过收尾状态

- **WHEN** 正在启动或运行的子 Agent 收到取消请求或超过墙钟时间
- **THEN** 委派先进入 `cancelling`，收尾完成后分别进入 `cancelled` 或 `timed_out`

#### Scenario: 非法或重复终态转换

- **WHEN** 调用方尝试跳过必需状态、从终态恢复运行，或为同一委派提交冲突的第二个终态
- **THEN** 系统拒绝该转换并保留原状态和原终态结果

### Requirement: 失败与预算结果归一化

系统 SHALL 将请求拒绝、启动失败、执行失败、预算耗尽、墙钟超时、父级取消和确认中止映射为稳定的状态与 reason code 组合。轮数、工具数或 token 预算耗尽 SHALL 使用 `failed` 加 `budget_exceeded` 表达，不得为每种预算类型新增顶层生命周期状态；无法确认资源清理时 SHALL 在结果中标记 `cleanup_uncertain`，不得伪造清理成功。

#### Scenario: 预算耗尽

- **WHEN** 子 Agent 达到轮数、工具数或 token 预算上限
- **THEN** 结果状态为 `failed`，reason code 为 `budget_exceeded`，且结果明确说明是否存在清理不确定性

#### Scenario: 墙钟超时

- **WHEN** 子 Agent 超过请求允许的墙钟时间
- **THEN** 系统执行取消和收尾流程，最终结果状态为 `timed_out`，reason code 为 `timeout`

#### Scenario: 父级取消

- **WHEN** 父 Agent 取消仍在运行的子 Agent
- **THEN** 子 Agent 收到取消信号并完成收尾，最终结果状态为 `cancelled`，reason code 为 `parent_cancelled`

#### Scenario: 子运行失败

- **WHEN** 子 Agent 在启动、模型请求或工具执行阶段发生未被业务处理的失败
- **THEN** 结果状态为 `failed`，携带与失败阶段对应的稳定 reason code、可重试标识和副作用诊断

#### Scenario: 清理无法确认

- **WHEN** 取消或超时后的资源清理未能证明已经完成
- **THEN** 结果保留 `cancelled` 或 `timed_out` 状态，并将 `cleanup_uncertain` 设为真，而不是报告为已安全终止

### Requirement: 父子运行事件关联

属于委派或子运行的事件 SHALL 能通过 `delegation_id`、`parent_run_id`、`child_run_id`、`attempt_id` 和 `depth` 关联到同一次父子执行。父级委派事件的 `run_id` SHALL 表示父运行，子 Agent 原生事件的 `run_id` SHALL 表示子运行；关联字段不得覆盖或改写事件所属运行的 `run_id`。面向父级事件流的 Subagent envelope SHALL 使用明确的事件类型表达排队、启动、进度和终态，并保留 `subagent_status`、`child_phase`、子事件类型和父/子序列信息；其负载 SHALL 只包含有界的状态或操作摘要，不得包含完整子 transcript、内部对象或无界工具输出。

父级事件流中的 `sequence` SHALL 按事件所属的父或子 run 分别单调递增；当子事件被转发到父级总线时，系统 SHALL 另外提供不覆盖子序列的父级接收序列，以便消费者按父级到达顺序排序。排队阶段尚无 child_run_id 时允许只携带父级归属；child_run_id 可用后，后续子事件 SHALL 保留真实子 run_id。

#### Scenario: 父级事件关联子运行

- **WHEN** 父 Agent 发起或等待一次委派
- **THEN** 父级事件保留父 `run_id`，并携带对应的 `delegation_id` 和可用的 `child_run_id`

#### Scenario: 子级事件关联父运行

- **WHEN** 子 Agent 发布模型、工具或生命周期事件
- **THEN** 转发的 Subagent envelope 保留子事件的 `run_id` 和子序列，并携带 `delegation_id`、`parent_run_id`、`attempt_id`、`depth` 及父级接收序列

#### Scenario: 子事件负载保持有界

- **WHEN** 子 Agent 产生文本增量、工具进度、确认请求或生命周期变化
- **THEN** 父级事件流只接收有限的事件类型、阶段、工具摘要、状态和必要诊断，不复制完整消息、提示词或工具输出内容

#### Scenario: 父子序列彼此独立

- **WHEN** 父运行和子运行交错发布事件
- **THEN** 父级接收序列可以描述跨运行到达顺序，子序列仍只描述对应 child_run_id 内的顺序，二者不会互相覆盖或重置

#### Scenario: 旧事件消费者继续工作

- **WHEN** 消费者处理没有父子关联字段的既有单 Agent 事件
- **THEN** 事件仍可按原有 `run_id`、metadata 和事件类型消费，不要求消费者提供 Subagent 支持

#### Scenario: 委派终态唯一

- **WHEN** 委派执行成功、失败、超时、取消或拒绝后又收到迟到的过程事件或重复结果
- **THEN** 系统不改变已记录的终态，不再发布第二个冲突终态

### Requirement: Provider-neutral 子运行端口

系统 SHALL 通过只接收委派请求、可选事件回调并返回结构化终态结果的运行器端口执行子 Agent，并提供按 `delegation_id` 请求取消的能力。该端口不得要求调用方依赖具体模型 provider、工具类、会话管理器、持久化格式或 UI 实现。

#### Scenario: FakeRunner 可独立验证契约

- **WHEN** 测试使用不依赖外部服务的 FakeRunner 实现运行器端口
- **THEN** 测试可以独立验证状态转换、结果归一化、取消和终态唯一性

#### Scenario: 运行器执行完成

- **WHEN** 运行器接收合法请求并完成子运行
- **THEN** 执行调用返回一个与请求归属一致的终态 `SubagentResult`，而不是暴露子 Agent 的可变上下文或内部任务对象

#### Scenario: 取消请求可定位目标

- **WHEN** 调用方按 `delegation_id` 请求取消活动委派
- **THEN** 运行器只向对应的子运行传播取消，并由该委派返回最终取消或超时结果
