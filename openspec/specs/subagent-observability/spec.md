# subagent-observability Specification

## Purpose

为父会话提供安全、稳定且可解释的 Subagent 委派观测结果，让用户能够区分运行阶段、成功结论和失败诊断，同时不暴露子 Agent 的完整上下文或无界输出。

## Requirements

### Requirement: 委派状态投影

父会话的展示层 SHALL 消费顶层 `SUBAGENT_QUEUED`、`SUBAGENT_STARTED`、`SUBAGENT_PROGRESS` 和 `SUBAGENT_FINISHED` 事件，并按 `delegation_id` 为每次委派维护一份可更新的有限状态投影。投影 SHALL 至少区分排队、启动/运行、等待确认、取消中、已完成、失败、超时、已取消和拒绝；状态、阶段、耗时、profile、有限任务标签、child run 标识和稳定诊断 SHALL 来自结构化事件或结构化结果，而不是从自然语言、图标或完整工具输出推断。

#### Scenario: 委派进入排队和运行

- **WHEN** 父级依次收到合法委派的 `SUBAGENT_QUEUED` 与 `SUBAGENT_STARTED`
- **THEN** 展示层创建同一个 `delegation_id` 的投影，先显示排队，随后显示子运行已启动/运行，并在 child run 标识可用时补充该标识

#### Scenario: 子运行进入确认等待

- **WHEN** `SUBAGENT_PROGRESS` 表示子 Agent 正等待确认
- **THEN** 投影显示等待确认、子阶段、相关工具摘要和有界原因，不显示完整确认 prompt 或完整子 transcript

#### Scenario: 委派返回结构化结果

- **WHEN** 展示层收到 `SUBAGENT_FINISHED` 及其结构化结果
- **THEN** 投影显示唯一终态、有限摘要、适用的 reason code/诊断和清理状态；成功、失败、超时、取消或拒绝不会被渲染为同一种成功状态

### Requirement: 父子事件关联与隔离

展示层 SHALL 使用 `parent_run_id` 和 `delegation_id` 校验事件归属；child `session_id` 或 child `run_id` SHALL 只作为委派诊断，不得覆盖当前父会话的 run/session 状态。缺少必要归属、指向其它父 run、指向未知委派或在终态后到达的事件 SHALL 被忽略或记为有界诊断，不得创建重复投影、回退终态、修改父正文或影响其它委派。

#### Scenario: 乱序事件不覆盖其它委派

- **WHEN** 两个委派的进度和终态以交错顺序到达
- **THEN** 每个事件只更新匹配的 `delegation_id`，两个投影的阶段、结果和耗时彼此独立

#### Scenario: 迟到或错误父 run 事件

- **WHEN** 当前父运行已经变化，或某委派已发布终态后又收到旧进度/重复终态事件
- **THEN** 展示层保持当前父状态和已提交终态不变，不重新激活委派，也不追加重复内容

#### Scenario: 子事件不进入父正文

- **WHEN** 子 Agent 产生文本增量、工具结果或内部诊断
- **THEN** 父会话只接收 V5-06 定义的有限 Subagent 投影，子消息和无界工具输出不会作为父级普通 assistant、tool 或 error 正文显示

### Requirement: 有界结果与敏感信息过滤

展示输出 SHALL 对任务标签、摘要、诊断、确认原因和任意结果文本设置固定字符上限，并优先展示首行/结构化字段。输出 SHALL 不包含完整 prompt、显式 context、密钥、内部可变对象、完整子 transcript 或无界工具输出；结构化结果缺失或非法时 SHALL 显示有限的未知/无效诊断，不得猜测成功结论。

#### Scenario: 长摘要和诊断受控截断

- **WHEN** 事件或终态结果携带超过展示上限的摘要、原因或诊断
- **THEN** 展示层保留稳定终态和截断提示，单个投影和单行输出均保持有界

#### Scenario: 清理不确定保持诚实

- **WHEN** 终态结果包含 `cleanup_uncertain=true`
- **THEN** TUI/CLI 明确显示清理不确定诊断，不将其改写成普通完成或确认清理

### Requirement: Headless 委派状态输出

headless CLI 的一次性运行和交互循环 SHALL 为父级委派输出稳定、可脚本读取的状态/终态行，至少覆盖排队、启动/运行、等待确认、失败、超时、取消和完成。相同 `delegation_id` 的重复或过时事件 SHALL 不重复打印终态；行内容 SHALL 包含有限委派标识、状态、阶段或耗时以及适用的稳定错误码，并 SHALL 遵守本能力的敏感信息和长度边界。

#### Scenario: 一次性 headless 委派

- **WHEN** 使用 `--prompt` 执行包含 `delegate` 的父 Agent 任务
- **THEN** CLI 在最终父回复附近输出对应委派的有限状态/终态行，父回复仍保持正常输出顺序，子 Agent 的内部正文不被直接打印

#### Scenario: 交互 headless 委派

- **WHEN** headless 交互循环连续处理多个输入并产生多个委派
- **THEN** 每个输入的委派状态只归属于自己的 `delegation_id`，一次委派的失败或取消不会污染后续输入的状态行

#### Scenario: headless 终态诊断

- **WHEN** 委派因 `timeout`、`budget_exceeded`、`parent_cancelled`、权限拒绝或启动失败结束
- **THEN** CLI 显示对应稳定 reason code 和有限诊断，不以成功摘要替代失败结果，也不输出完整失败 payload
