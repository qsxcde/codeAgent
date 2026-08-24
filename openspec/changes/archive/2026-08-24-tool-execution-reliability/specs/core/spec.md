## MODIFIED Requirements

### Requirement: ReAct 循环执行

一轮对话 SHALL 以循环方式执行:先调用模型,若模型请求工具则执行工具并把结果并入消息历史后再次调用模型,直到模型产出无工具调用的最终回复;循环 SHALL 有最大轮数上限。模型工具调用参数无法解析或不是对象时,系统 SHALL 将该调用标记为参数错误、不得执行真实工具,并把可诊断的错误结果并入消息历史后继续循环,使模型有机会重新生成调用。

#### Scenario: 直接回复结束循环

- **WHEN** 模型首轮产出无工具调用的回复
- **THEN** 该回复作为最终回复,循环结束

#### Scenario: 工具调用后继续循环

- **WHEN** 模型产出带有合法参数的工具调用
- **THEN** 工具被执行、结果并入消息历史,循环继续调用模型

#### Scenario: 工具参数解析失败

- **WHEN** 模型产出非法 JSON、截断 JSON 或非对象工具参数
- **THEN** 真实工具不得执行,该调用产生带工具名、调用 id 和解析原因的错误结果并入消息历史,循环允许模型重新生成调用

#### Scenario: 循环上限

- **WHEN** 模型连续调用工具达到循环上限
- **THEN** 本轮中止并以友好提示结束,不进入死循环

### Requirement: 事件契约

执行过程 SHALL 以事件流对外暴露,事件类型与既有契约一致并增量扩展(11 类):`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage / confirmation_requested`;执行失败时 SHALL 先回滚再发 `error`;被取消时 SHALL 发 `run_cancelled`;工具调用需用户确认时 SHALL 发 `confirmation_requested`(携带请求标识、工具、摘要与原因),订阅方据此呈现确认交互。工具结果 metadata SHALL 可区分普通失败、参数解析失败、超时、取消、拒绝和清理完成状态,既有事件类型和既有字段语义 SHALL 保持兼容。

#### Scenario: 执行进度可订阅

- **WHEN** 一轮对话执行中
- **THEN** 订阅方按既有事件类型感知进度(文本增量、思考增量、工具调用与结果、用量),无需等待最终返回值

#### Scenario: 失败与取消语义

- **WHEN** 执行失败
- **THEN** 本轮消息已回滚,且订阅方收到 `error` 事件
- **WHEN** 执行被取消
- **THEN** 本轮消息已回滚,且订阅方收到 `run_cancelled` 事件

#### Scenario: 确认请求可订阅

- **WHEN** 工具调用需用户确认
- **THEN** 订阅方收到 `confirmation_requested` 事件,携带请求标识、工具名、摘要与确认原因;既有事件类型语义不变(契约只增不改)

#### Scenario: 工具状态可诊断

- **WHEN** 工具调用因参数错误、超时、取消、拒绝或清理完成而结束
- **THEN** 对应 `tool_result` 事件 metadata 携带稳定状态标识和必要的诊断信息,用户界面无需解析错误文本即可展示状态

## ADDED Requirements

### Requirement: 受控工具执行

工具调用执行 SHALL 受运行时并发上限和取消语义约束。系统 SHALL 保持同一批工具调用的结果顺序与调用顺序一致;达到并发上限的调用 SHALL 等待而不是无限创建任务;运行取消或超时 SHALL 触发对应工具的清理流程,无法强制抢占的同步工具 SHALL 明确报告其降级状态。

#### Scenario: 并发上限

- **WHEN** 一批模型响应包含超过运行时并发上限的可执行工具调用
- **THEN** 同时运行的工具数量不超过上限,其余调用按确定顺序排队,结果仍按原调用顺序回填

#### Scenario: 工具超时

- **WHEN** 工具执行超过会话配置的超时时间
- **THEN** 工具被标记为超时,执行器触发清理,并向模型回填错误结果;若底层工具无法强制终止,结果 SHALL 明确标记为“停止等待但后台清理未确认”

#### Scenario: 运行中止

- **WHEN** 用户在工具执行期间调用 abort
- **THEN** 当前工具执行收到取消信号并进入清理流程,会话发出 `run_cancelled`,本轮未完成消息不落盘

#### Scenario: 单工具失败不影响同批调用

- **WHEN** 同一批工具中一个调用参数错误、超时或执行失败
- **THEN** 该调用回填独立错误结果,其它调用按策略继续或完成,错误不得污染其它 tool_call_id
