## MODIFIED Requirements

### Requirement: 事件契约

Agent Runtime SHALL 以结构化事件暴露 Agent、turn、message、模型请求、模型流和工具执行生命周期；核心事件至少包括 `agent_start`、`agent_end`、`turn_start`、`turn_end`、`message_start`、`message_update`、`message_end`、`model_request_started`、`model_request_finished`、`tool_execution_queued`、`tool_execution_start`、`tool_execution_update`、`tool_execution_end`、`usage`、`context_budget`、`context_preflight`、`error` 和 `aborted`。每个属于一次运行的事件 SHALL 携带稳定的 `run_id`；工具生命周期事件 SHALL 携带 `tool_call_id`、`operation_id` 和工具名，并在 session 适配边界补充 `session_id`。事件 SHALL 能区分排队、执行中、过程更新和唯一终态，且订阅方无需解析错误文本判断工具状态、清理状态或输出完整性。Session started、restore、compaction、persistence 和 confirmation 等事件 SHALL 由 session/app 层定义或适配，不再作为 core Agent 事件的职责。

#### Scenario: Agent 生命周期可订阅

- **WHEN** 一次 Agent prompt 或 continue 开始并完成
- **THEN** 订阅方依次可感知 Agent 开始、turn、消息生命周期和 Agent 结束事件

#### Scenario: 流式输出可订阅

- **WHEN** 模型产生文本、thinking 或工具参数增量
- **THEN** 订阅方收到对应的结构化 message update，无需等待最终回复

#### Scenario: 模型请求边界可订阅

- **WHEN** 一次模型请求开始并正常、失败或取消结束
- **THEN** 订阅方收到一次 `model_request_started` 和一次带结果状态的 `model_request_finished` 事件，流式内容、预算和用量位于两者之间

#### Scenario: 工具生命周期可订阅

- **WHEN** 工具调用进入执行批次并等待并发槽位、确认决策或实际开始执行
- **THEN** 订阅方分别收到带同一 `tool_call_id` 和 `operation_id` 的排队、开始或等待确认相关事件；开始事件只表示实际执行已经获得许可并占用执行槽位，完成时再收到对应终态事件

#### Scenario: 工具进度与终态可订阅

- **WHEN** 工具产生进度、正常完成、失败、超时、取消或清理不确定收尾
- **THEN** 订阅方收到带稳定调用归属、机器可读状态、耗时、错误和清理诊断的更新及终态事件；每个调用最多有一个终态

#### Scenario: 执行进度可订阅

- **WHEN** Agent 执行模型请求或工具调用
- **THEN** 订阅方可通过 Agent 生命周期事件感知文本、thinking、工具调用和工具结果进度,无需等待最终返回值

#### Scenario: 预算判定可订阅

- **WHEN** Agent 准备一次模型请求并完成预算前置判定
- **THEN** 订阅方收到包含判定状态、输入估算、输入预算、余量和窗口来源的 `context_preflight` 事件

#### Scenario: 失败与取消语义

- **WHEN** Agent 执行失败或收到取消信号
- **THEN** core 发出结构化 error 或 aborted 事件，由 session 层决定回滚和持久化；已经进入执行的工具调用仍通过工具终态事件报告取消和清理事实

#### Scenario: 确认请求可订阅

- **WHEN** 上层安全适配器需要用户确认工具调用
- **THEN** session/app 层发出 `confirmation_requested` 事件并将最终 allow/block 决策回传 hook，core 不直接管理确认队列

#### Scenario: 工具状态可诊断

- **WHEN** 工具因参数错误、超时、取消、拒绝或清理未确认而结束
- **THEN** 工具事件和结果携带稳定状态、operation id、清理状态和可用的输出完整性信息，订阅方无需解析错误文本

#### Scenario: 并发事件按调用归属

- **WHEN** 同一批工具并行执行且完成事件以不同顺序到达
- **THEN** 每个事件按 `tool_call_id` 和 `operation_id` 归属到原始调用；事件到达顺序不改变模型结果按原始调用顺序回填的语义

#### Scenario: Session 事件由上层适配

- **WHEN** session 层需要广播会话创建、恢复、压缩或确认状态
- **THEN** session/app 层将 Agent 事件转换或补充为 Session 事件，core Agent Runtime 不引入持久化或 UI 生命周期

#### Scenario: 运行终态唯一

- **WHEN** 一个运行进入 completed、failed 或 cancelled 任一终态
- **THEN** 该运行只发布一次终态，终态之后不再发布属于该运行的普通过程事件；已经发布的工具终态不得因重复结果事件被改写
