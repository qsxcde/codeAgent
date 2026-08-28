## MODIFIED Requirements

### Requirement: 受控工具执行

工具调用 SHALL 经统一的 AgentTool 执行协议运行，执行器 SHALL 支持可配置的并行或串行模式、运行期并发上限、超时、取消和进度更新。系统 SHALL 保持同一批工具结果向模型回填时的调用顺序；达到并发上限的调用 SHALL 等待；取消或超时 SHALL 触发工具清理，并明确报告清理已确认、清理失败或清理不确定的状态。对于无法抢占的同步工具，执行器 SHALL 不得把停止等待误报为工具已经终止。

#### Scenario: 并发上限

- **WHEN** 一批模型响应包含超过执行器并发上限的工具调用
- **THEN** 同时运行的工具数量不超过上限，其余调用等待，结果仍按原调用顺序回填

#### Scenario: 工具执行模式

- **WHEN** Agent 配置为 parallel 或 sequential，或单个工具声明覆盖模式
- **THEN** 执行器按有效模式运行，并在事件中保持真实完成顺序与回填顺序的语义可区分

#### Scenario: 工具超时

- **WHEN** 工具执行超过配置的超时时间
- **THEN** 工具被标记为 timed_out，执行器触发清理并向模型回填错误结果；若无法证明工具和其派生资源已经终止，结果 SHALL 标记 cleanup_uncertain

#### Scenario: 运行中止

- **WHEN** Agent 收到取消信号且工具正在执行
- **THEN** 工具收到取消信号并进入清理流程，未完成调用不得继续占用执行器槽位；清理完成前运行不得报告为已完全结束

#### Scenario: 单工具失败不影响同批调用

- **WHEN** 同一批工具中一个调用参数错误、超时或执行失败
- **THEN** 该调用回填独立错误结果，其它调用按执行策略继续或完成，错误不得污染其它 tool_call_id

#### Scenario: 清理结果可验证

- **WHEN** 工具清理接口执行成功、失败或不受支持
- **THEN** 工具结果和执行事件分别标记对应清理状态，调用方能够区分 confirmed、failed、uncertain 和 unsupported

### Requirement: 运行干预

Agent Runtime SHALL 支持 prompt、continue、abort、steer 和 follow-up 五类运行控制。steer 消息 SHALL 在当前工具批次结束后、下一次模型请求前注入；follow-up 消息 SHALL 仅在当前 Agent 判断本轮完成后启动新的 turn；continue SHALL 从已有 user 或 tool result 上下文恢复，不得重复添加 prompt。abort SHALL 先发出取消请求，再等待模型、工具和确认等待点完成取消传播与清理；只有收尾完成后，运行才可报告为 cancelled。

#### Scenario: 中断

- **WHEN** 调用方请求 abort
- **THEN** 当前模型或工具操作收到取消信号，Agent 发出 aborted/error 收尾事件；调用方能够等待实际清理完成后继续使用该上下文

#### Scenario: 重复中断

- **WHEN** 调用方在同一运行上重复请求 abort
- **THEN** 后续请求不创建新的取消流程、不破坏已有收尾，并返回该运行当前的取消状态

#### Scenario: steer 注入

- **WHEN** Agent 运行期间收到 steer 消息
- **THEN** 当前工具批次完成后消息被追加到内存上下文，下一次模型请求优先处理该消息，且不会启动旁路 run

#### Scenario: follow-up 排队

- **WHEN** Agent 已完成当前工具链且存在 follow-up 消息
- **THEN** follow-up 被作为新的 user 消息启动后续 turn，不会与当前工具链交错

#### Scenario: continue

- **WHEN** 调用方调用 continue 且上下文最后一条消息是 user 或 tool result
- **THEN** Agent 从该上下文继续执行；若最后一条是 assistant，调用被拒绝并返回明确错误

#### Scenario: 追问与注入

- **WHEN** 调用方提交 follow-up 或 steer 消息
- **THEN** follow-up 在当前 Agent 完成后启动新 turn，steer 在当前工具批次结束后于下一次模型请求前注入

#### Scenario: 取消时排队请求收尾

- **WHEN** 运行在处理 follow-up 或等待 steer 注入时被取消
- **THEN** 所有排队请求得到明确的取消结果或异常，不留下悬挂 Future，也不启动新的 turn
