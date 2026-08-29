## MODIFIED Requirements

### Requirement: ReAct 循环执行

Agent Runtime SHALL 以纯内存循环执行“模型响应→工具执行→继续或结束”:模型产出无工具调用的最终消息后结束;模型产出工具调用时,系统 SHALL 执行工具、将结果按调用顺序加入 Agent 上下文并继续请求模型;循环 SHALL 有最大轮数上限。模型适配器 SHALL 在进入 core 前将 provider 原始流事件和工具参数转换为 core 统一形状,core 不直接解析 provider 协议。每次模型请求 SHALL 在最终临时上下文准备完成后、调用模型前执行上下文预算前置判定；判定阻断时不得进入模型或工具副作用路径。

#### Scenario: 直接回复结束循环

- **WHEN** 模型首轮产出无工具调用的回复
- **THEN** 该回复作为最终 Agent 消息,循环结束并返回本轮新增消息

#### Scenario: 工具调用后继续循环

- **WHEN** 模型产出带有合法参数的工具调用
- **THEN** 工具被执行、结果按 tool_call_id 加入 Agent 上下文,循环继续调用模型

#### Scenario: 工具参数解析失败

- **WHEN** 模型适配器向 core 提供参数错误的工具调用
- **THEN** 真实工具不得执行,该调用产生带工具名、调用 id 和错误原因的结果并入上下文,循环允许模型重新生成调用

#### Scenario: 循环上限

- **WHEN** 模型连续调用工具达到循环上限
- **THEN** Agent Runtime 中止本轮并返回可识别的循环超限错误,不进入死循环

#### Scenario: 从已有上下文继续

- **WHEN** 调用方从最后一条 user 或 tool result 消息继续执行
- **THEN** Agent Runtime 不重复追加原始 user 消息,直接从已有上下文开始下一轮模型调用

#### Scenario: 请求前预算阻断

- **WHEN** 最终模型上下文被预算前置判定为超限或不确定策略要求阻断
- **THEN** Agent Runtime 在调用模型前发布结构化预算错误并结束本轮,不执行新的工具调用

### Requirement: 事件契约

Agent Runtime SHALL 以结构化事件暴露 Agent、turn、message、模型流和工具执行生命周期;核心事件至少包括 `agent_start`、`agent_end`、`turn_start`、`turn_end`、`message_start`、`message_update`、`message_end`、`tool_execution_start`、`tool_execution_update`、`tool_execution_end`、`usage`、`context_budget`、`context_preflight`、`error` 和 `aborted`。每个属于一次运行的事件 SHALL 携带稳定的 `run_id`,并在 session 适配边界补充 `session_id`;事件 SHALL 能区分过程事件与唯一终态。Session started、restore、compaction、persistence 和 confirmation 等事件 SHALL 由 session/app 层定义或适配,不再作为 core Agent 事件的职责。事件负载 SHALL 使用稳定的结构化字段,订阅方无需解析错误文本判断工具状态或预算状态。

#### Scenario: Agent 生命周期可订阅

- **WHEN** 一次 Agent prompt 或 continue 开始并完成
- **THEN** 订阅方依次可感知 Agent 开始、turn、消息生命周期和 Agent 结束事件

#### Scenario: 流式输出可订阅

- **WHEN** 模型产生文本、thinking 或工具参数增量
- **THEN** 订阅方收到对应的结构化 message update,无需等待最终回复

#### Scenario: 工具生命周期可订阅

- **WHEN** 工具开始、产生进度或完成
- **THEN** 订阅方收到带 tool_call_id、工具名、参数或结果状态的工具执行事件

#### Scenario: 执行进度可订阅

- **WHEN** Agent 执行模型请求或工具调用
- **THEN** 订阅方可通过 Agent 生命周期事件感知文本、thinking、工具调用和工具结果进度,无需等待最终返回值

#### Scenario: 预算判定可订阅

- **WHEN** Agent 准备一次模型请求并完成预算前置判定
- **THEN** 订阅方收到包含判定状态、输入估算、输入预算、余量和窗口来源的 `context_preflight` 事件

#### Scenario: 失败与取消语义

- **WHEN** Agent 执行失败或收到取消信号
- **THEN** core 发出结构化 error 或 aborted 事件,由 session 层决定回滚和持久化

#### Scenario: 确认请求可订阅

- **WHEN** 上层安全适配器需要用户确认工具调用
- **THEN** session/app 层发出 confirmation_requested 事件并将最终 allow/block 决策回传 hook,core 不直接管理确认队列

#### Scenario: 工具状态可诊断

- **WHEN** 工具因参数错误、超时、取消、拒绝或清理未确认而结束
- **THEN** 工具事件和结果携带稳定状态、operation id 和清理诊断,订阅方无需解析错误文本

#### Scenario: Session 事件由上层适配

- **WHEN** session 层需要广播会话创建、恢复、压缩或确认状态
- **THEN** session/app 层将 Agent 事件转换或补充为 Session 事件,core Agent Runtime 不引入持久化或 UI 生命周期

#### Scenario: 运行终态唯一

- **WHEN** 一个运行进入 completed、failed 或 cancelled 任一终态
- **THEN** 该运行只发布一次终态,终态之后不再发布属于该运行的普通过程事件
