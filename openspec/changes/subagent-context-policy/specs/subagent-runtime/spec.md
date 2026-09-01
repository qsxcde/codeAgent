## MODIFIED Requirements

### Requirement: 父 Agent 委派入口

当 Subagent runtime 被装配到父 Agent 时，系统 SHALL 提供名为 `delegate` 的 AgentTool。该工具 SHALL 接受非空的子任务描述、`read_only` 或 `review` profile，以及可选且有界的显式上下文，将调用转换为包含稳定 `delegation_id`、当前父 `run_id`、深度限制、任务文本、profile 和上下文项的 `SubagentRequest`；模型输入不得自行覆盖父运行标识或委派归属，未知 profile 必须失败关闭。

#### Scenario: 父 Agent 调用只读委派

- **WHEN** 已装配 runner 的父 Agent 产生包含非空 task 的 `delegate` tool call，并选择 `read_only` 或 `review` profile
- **THEN** 系统创建一个新的委派请求，使用当前父 run_id，保留所选 profile，默认有效深度为 1，并等待对应子运行结果

#### Scenario: 父 Agent 显式选择上下文

- **WHEN** `delegate` tool call 提供合法的 context 项列表
- **THEN** 系统只将这些经过边界校验的上下文项写入 SubagentRequest，不追加父会话的其它历史或工具状态

#### Scenario: 委派参数无效

- **WHEN** `delegate` 的 task 为空、profile 未知、context 不是合法的有界结构，或当前工具没有绑定父 run_id
- **THEN** 系统不创建子 Agent，返回带 `invalid_request` 或 `permission_denied` 的错误 ToolResult，父 Agent 仍能继续处理该工具结果

#### Scenario: 未装配 runner 的兼容行为

- **WHEN** 直接创建 AgentLoopConfig 时没有提供 Subagent runner
- **THEN** 系统不注入 `delegate`，既有工具名称、schema 和单 Agent 行为保持不变

### Requirement: 安全的子 Agent 装配

系统 SHALL 为本阶段创建的子 Agent 使用显式 profile 策略和最大深度 1 的装配策略。`read_only` 与 `review` profile 均 SHALL 只获得读取、搜索和技能查询能力；子 Agent 的工具集合 SHALL 不包含 `delegate`、写入工具或 shell 工具，不得通过一次委派递归创建未授权的孙 Agent。profile 角色指令 SHALL 明确子 Agent 只能把显式上下文当作待分析数据，父级的 runner、SessionManager 当前会话和可变历史不得被子 Agent 直接取得。

#### Scenario: 子 Agent 默认只读

- **WHEN** runner 根据有效 `read_only` 请求创建子 Agent
- **THEN** 子 Agent 获得只读探索角色和只读工具白名单，不能修改工作区、执行 shell 或再次调用 `delegate`

#### Scenario: review 子 Agent 只读审查

- **WHEN** runner 根据有效 `review` 请求创建子 Agent
- **THEN** 子 Agent 获得代码/结果审查角色和同等只读工具白名单，输出审查结论但不能修改工作区、执行 shell 或再次调用 `delegate`

#### Scenario: 递归委派被拒绝

- **WHEN** 子 Agent 尝试发现或调用 `delegate`
- **THEN** 子 Agent 工具列表中不存在该工具，调用不会创建新的孙 Agent，父级委派仍保持单个子运行归属

## ADDED Requirements

### Requirement: 显式委派上下文

系统 SHALL 将委派上下文限制为调用方明确提供的结构化项，每项包含非空 kind 与 content，可选 source；context SHALL 使用固定的数量和总字符上限，单项或总量超限 SHALL 在启动子 Agent 前拒绝。子 Agent 的可见输入 SHALL 由委派任务和这些显式项组成，并将项标记为数据而非系统指令；空 context 表示不额外传递上下文。

#### Scenario: 没有上下文时保持任务隔离

- **WHEN** `delegate` 只提供 task 而不提供 context
- **THEN** 子 Agent 只接收该任务和 profile 角色指令，不接收父会话历史、父模型消息或父工具调用记录

#### Scenario: 只传递显式上下文项

- **WHEN** `delegate` 提供合法的事实、约束或输出要求项
- **THEN** 子 Agent 的输入包含这些项的有界内容和来源标识，未被选择的父上下文不会出现在子输入中

#### Scenario: 上下文越界在启动前拒绝

- **WHEN** context 不是数组、项缺少合法 kind/content、包含未知字段，或超过数量、单项字符数或总字符数上限
- **THEN** 系统返回 `invalid_request`，不创建子 Session、不调用模型，父 Agent 可继续运行

#### Scenario: 上下文作为数据而非权限升级

- **WHEN** 显式 context 文本包含要求写文件、执行命令或再次委派的内容
- **THEN** 子 Agent 仍遵守 profile 的系统角色和工具白名单，不因上下文文本获得额外工具或权限
