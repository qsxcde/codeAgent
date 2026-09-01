## MODIFIED Requirements

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
