## MODIFIED Requirements

### Requirement: 消息归约

Agent Runtime SHALL 维护有序的内存消息列表：工具结果 SHALL 按 tool_call_id 关联到对应工具调用；消息 SHALL 具备运行期唯一 id；每次运行 SHALL 在独立的工作消息列表中归约新增消息，只有运行成功且 session 提交边界完成后才可合并到会话历史。执行失败或取消时，调用方 SHALL 能丢弃本轮全部新增消息而保留此前上下文。持久化父子关系、分支记录和压缩记录 SHALL 由 session 层负责，不成为 core 消息模型的应用依赖。

#### Scenario: 工具结果按调用归属

- **WHEN** 一个模型回复携带多个工具调用且工具并行完成
- **THEN** 每个工具结果按 tool_call_id 归属，向模型提交的结果顺序与原始调用顺序一致，成功与失败结果互不污染

#### Scenario: 失败回滚

- **WHEN** Agent Runtime 本轮执行失败或被取消
- **THEN** 本轮新增消息可从内存上下文移除，此前上下文保持完整，session 层不得提交本轮不完整消息

#### Scenario: 消息 id 稳定有序

- **WHEN** Agent Runtime 创建 user、assistant 或 tool result 消息
- **THEN** 每条消息带有唯一 id，可供工具结果归属、事件关联和上层持久化引用

#### Scenario: 提交边界隔离

- **WHEN** Agent 已产生新增消息但 session 尚未完成持久化提交
- **THEN** 新增消息不会被视为已提交历史；提交失败时可以完整丢弃，不影响此前已持久化上下文
